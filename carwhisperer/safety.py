"""Whitelist of what may be sent to the adapter and, through it, to the car.

The rule is allow-list, not block-list: a request goes out only if it is a known
read service. Anything that clears, writes, actuates, unlocks or reprograms is
refused before it reaches the Bluetooth link.
"""

# OBD-II read services, KWP2000 read services and UDS read services.
ALLOWED_SERVICES = {
    0x01, 0x02, 0x03, 0x07, 0x09, 0x0A,   # OBD: live data, freeze frame, DTCs, vehicle info
    0x1A, 0x18, 0x21,                     # KWP2000: ReadEcuIdentification, ReadDTCByStatus, ReadDataByLocalId
    0x19, 0x22,                           # UDS: ReadDTCInformation, ReadDataByIdentifier
    0x3E,                                 # TesterPresent
}
# Session control is allowed only for the sessions that unlock nothing writable.
ALLOWED_EXACT = {bytes([0x10, 0x01]), bytes([0x10, 0x03]), bytes([0x10, 0x81])}

# Adapter commands that write to the adapter's non-volatile memory, or make it
# acknowledge frames while monitoring. ATPPS (print the parameter table) is fine.
FORBIDDEN_AT_PREFIXES = ("ATPP", "ATSD", "AT@3", "ATCSM0")
ALLOWED_AT_EXACT = {"ATPPS"}


class Refused(RuntimeError):
    """Raised when a command is not on the read-only whitelist."""


def check_payload(payload: bytes) -> None:
    if not payload:
        raise Refused("empty request")
    if payload in ALLOWED_EXACT:
        return
    if payload[0] == 0x10:
        raise Refused(f"session {payload.hex().upper()} is not a read-only session")
    if payload[0] in ALLOWED_SERVICES:
        return
    raise Refused(f"service 0x{payload[0]:02X} is not a read-only service")


def check_command(text: str, raw_frames: bool) -> None:
    """Validate one line before it is written to the adapter.

    raw_frames tells how the adapter will interpret hex data: with ATCAF0 the
    first byte is the ISO-TP PCI byte, otherwise the first byte is the service.
    """
    up = text.strip().upper().replace(" ", "")
    if up.startswith("AT"):
        if up in ALLOWED_AT_EXACT:
            return
        if up.startswith(FORBIDDEN_AT_PREFIXES):
            raise Refused(f"adapter command {up} is not allowed")
        return
    try:
        data = bytes.fromhex(up)
    except ValueError:
        raise Refused(f"not hex data: {text!r}") from None
    if not raw_frames:
        check_payload(data)
        return
    kind = data[0] >> 4
    if kind == 0x3:                       # flow control: carries no service
        if len(data) != 3:
            raise Refused("flow control frame must be 3 bytes")
        return
    if kind == 0x0:                       # single frame: length nibble must match
        if (data[0] & 0x0F) != len(data) - 1:
            raise Refused("single-frame length does not match its PCI byte")
        check_payload(data[1:])
        return
    raise Refused("only single frames and flow control may be sent in raw mode")
