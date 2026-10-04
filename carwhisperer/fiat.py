"""What is known about one car: Fiat Grande Punto (199) 1.4 8V, engine 350A1000,
South African market, Magneti Marelli IAW 5SF9. See docs/protocol.md for the evidence."""

MODULES = {0x10: "engine (Marelli IAW 5SF9)", 0x28: "ABS", 0x30: "electric power steering", 0x40: "body computer"}

# Standard UDS identification DIDs this ECU answers, in the default session.
IDENT_DIDS = {
    0xF180: "boot software id", 0xF181: "application software id", 0xF182: "application data id",
    0xF186: "active session", 0xF187: "spare part number", 0xF18C: "ECU serial number", 0xF190: "VIN",
    0xF192: "supplier hardware number", 0xF193: "supplier hardware version",
    0xF194: "supplier software number", 0xF195: "supplier software version", 0xF196: "ECU name",
    0xF1A0: "identification block (Fiat)", 0xF1A4: "Fiat F1A4", 0xF1A5: "Fiat F1A5",
}
PRIVATE_DIDS = {0xF18C, 0xF190}   # serial number and VIN: masked unless asked for

# name, unit, scaling, confidence
LIVE_DIDS = {
    0x1000: ("engine speed", "rpm", lambda v: v / 4, "confirmed against the CAN broadcast"),
    0x1003: ("coolant temperature", "°C", lambda v: v - 40, "matches the broadcast byte; offset assumed"),
    0x1004: ("battery voltage", "V", lambda v: v / 10, "confirmed against the adapter's voltmeter"),
    0x186B: ("idle speed target", "rpm", lambda v: v / 4, "engine speed follows it; rises with A/C load"),
    0x181F: ("manifold pressure", "mbar", lambda v: v, "likely; tracks load"),
}

# Broadcast frames on the C-CAN bus (29-bit, 500 kbps). The last byte of the ID is the sender.
BROADCAST = {
    "0618A001": "engine: speed in bytes 2-3 (1 rpm/bit), pedal in byte 7",
    "0A18A001": "engine: coolant temperature in byte 3 (raw - 40 °C)",
    "0628A001": "engine: throttle plate position in byte 4 (counts)",
    "0210A006": "ABS: vehicle speed",
    "0218A006": "ABS: wheel speeds",
    "0220A006": "ABS: unidentified",
    "0030A002": "steering: angle and rate",
    "0A18A002": "steering: status",
    "0810A000": "body computer: brake switch",
    "0A18A000": "body computer: ambient temperature, fuel level, doors",
}
RPM_FRAME = "0618A001"


def rpm_from_frame(data: bytes) -> int:
    return int.from_bytes(data[2:4], "big")


DTC_STATUS_BITS = ("testFailed", "testFailedThisOperationCycle", "pendingDTC", "confirmedDTC",
                   "testNotCompletedSinceLastClear", "testFailedSinceLastClear",
                   "testNotCompletedThisOperationCycle", "warningIndicatorRequested")


def decode_dtcs(data: bytes) -> list[tuple[str, int, list[str]]]:
    """Decode a 59 02 reply: [(code like 'P0135-14', status byte, [status flags])]."""
    if not data or data[0] != 0x59 or len(data) < 3:
        return []
    out = []
    records = data[3:]
    for i in range(0, len(records) - 3, 4):
        hi, mid, failure_type, status = records[i:i + 4]
        code = f"{'PCBU'[hi >> 6]}{(hi >> 4) & 3}{hi & 0x0F:X}{mid:02X}-{failure_type:02X}"
        out.append((code, status, [n for b, n in enumerate(DTC_STATUS_BITS) if status >> b & 1]))
    return out
