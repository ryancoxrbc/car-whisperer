"""UDS over ISO 15765 on 29-bit CAN, with ISO-TP frames that are NOT padded.

The Marelli IAW 5SF9 ignores any diagnostic frame padded to 8 bytes, which is
what an ELM327 sends by default. So formatting is switched off (ATCAF0), the
real data length is used (ATV1) and ISO-TP is done here.
"""
import asyncio
import re

from .elm import Elm

NRC = {
    0x10: "generalReject", 0x11: "serviceNotSupported", 0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLength", 0x22: "conditionsNotCorrect", 0x31: "requestOutOfRange",
    0x33: "securityAccessDenied", 0x78: "responsePending",
    0x7E: "subFunctionNotSupportedInActiveSession", 0x7F: "serviceNotSupportedInActiveSession",
}


def parse_frames(resp: str, rx_id: str) -> list[bytes]:
    """Pick the data bytes of every frame with the expected arbitration ID."""
    out = []
    for line in resp.split("\n"):
        line = line.strip().replace(" ", "").upper()
        body = line[len(rx_id):]
        if line.startswith(rx_id) and body and len(body) % 2 == 0 and re.fullmatch(r"[0-9A-F]+", body):
            out.append(bytes.fromhex(body))
    return out


def reassemble(frames: list[bytes]) -> tuple[bytes | None, bool]:
    """Return (payload, complete) from a single frame or first frame plus consecutive frames."""
    if not frames:
        return None, False
    first = frames[0]
    kind = first[0] >> 4
    if kind == 0:
        return first[1:1 + (first[0] & 0x0F)], True
    if kind != 1:
        return None, False
    total = ((first[0] & 0x0F) << 8) | first[1]
    buf = bytearray(first[2:])
    expect = 1
    for cf in frames[1:]:
        if cf[0] >> 4 == 2 and (cf[0] & 0x0F) == (expect & 0x0F):
            buf.extend(cf[1:])
            expect += 1
    return bytes(buf[:total]), len(buf) >= total


class Uds:
    def __init__(self, elm: Elm, target: int = 0x10, tester: int = 0xF1):
        self.elm, self.target, self.tester = elm, target, tester

    @property
    def tx_id(self) -> str:
        return f"18DA{self.target:02X}{self.tester:02X}"

    @property
    def rx_id(self) -> str:
        return f"18DA{self.tester:02X}{self.target:02X}"

    async def setup(self):
        e = self.elm
        for c in ("ATSP7",                      # ISO 15765-4, 29-bit, 500 kbps
                  "ATCP18",                     # top byte of the 29-bit ID
                  "ATCAF0", "ATV1",             # raw frames, true DLC: no padding
                  "ATH1", "ATAT0", "ATST64"):   # show IDs, fixed 400 ms response window
            await e.cmd(c)
        await self.retarget(self.target)
        # Let the adapter answer First Frames itself. Doing it from the host over BLE is
        # too slow and the ECU gives up after the first frame.
        await e.cmd("ATFCSD300000")
        await e.cmd("ATFCSM1")
        await e.cmd("ATCFC1")

    async def retarget(self, target: int):
        self.target = target
        await self.elm.cmd(f"ATSH{self.tx_id[2:]}")
        await self.elm.cmd(f"ATCRA{self.rx_id}")
        await self.elm.cmd(f"ATFCSH{self.tx_id}")

    async def request(self, payload: bytes, timeout: float = 4.0) -> bytes | None:
        """Send one request (max 7 bytes) and return the reassembled reply, or None."""
        if not 1 <= len(payload) <= 7:
            raise ValueError("only single-frame requests are supported")
        e = self.elm
        verbose, e.verbose = e.verbose, False
        try:
            resp = await e.cmd(f"{len(payload):02X}{payload.hex().upper()}", timeout=timeout)
            for _ in range(6):
                data, complete = reassemble(parse_frames(resp, self.rx_id))
                if data is None:
                    return None
                if not complete:                # adapter did not send flow control: do it by hand
                    more = await e.cmd("300000", timeout=timeout)
                    data, _ = reassemble(parse_frames(resp + "\n" + more, self.rx_id))
                if len(data) >= 3 and data[0] == 0x7F and data[2] == 0x78:
                    await asyncio.sleep(0.3)    # responsePending: listen again
                    resp = await e.cmd("023E80", timeout=timeout)
                    continue
                return data
            return data
        finally:
            e.verbose = verbose

    async def read_did(self, did: int, timeout: float = 4.0) -> bytes | None:
        return await self.request(bytes([0x22, did >> 8, did & 0xFF]), timeout=timeout)


def positive(data: bytes | None) -> bool:
    return bool(data) and data[0] != 0x7F


def describe(data: bytes | None) -> str:
    if data is None:
        return "no response"
    if data[0] == 0x7F and len(data) >= 3:
        return f"negative: service {data[1]:02X}, code {data[2]:02X} ({NRC.get(data[2], 'unknown')})"
    text = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
    return f"{data.hex().upper()}  '{text}'"
