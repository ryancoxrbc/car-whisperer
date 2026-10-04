"""ELM327 over Bluetooth Low Energy (Veepeak OBDCheck BLE and similar)."""
import asyncio
import os

from bleak import BleakClient, BleakScanner

from .safety import check_command

SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"   # adapter -> host
WRITE_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"    # host -> adapter
DEFAULT_NAME = "VEEPEAK"
STATUS_WORDS = ("NO DATA", "UNABLE TO CONNECT", "CAN ERROR", "BUS INIT", "ERROR", "STOPPED", "BUFFER FULL", "?")


def is_status(resp: str) -> bool:
    """True when the adapter answered with a status word instead of bus data."""
    return (not resp) or any(w in resp for w in STATUS_WORDS)


class Elm:
    def __init__(self, client: BleakClient, verbose: bool = True):
        self.c = client
        self.verbose = verbose
        self.raw_frames = False            # True after ATCAF0
        self._buf = bytearray()
        self._prompt = asyncio.Event()
        service = client.services.get_service(SERVICE_UUID)
        # The UUID FFF1 exists in two services on this adapter, so look it up inside FFF0.
        self._notify = service.get_characteristic(NOTIFY_UUID)
        self._write_char = service.get_characteristic(WRITE_UUID)

    def _on_notify(self, _handle, data: bytearray):
        self._buf += data
        if b">" in data:
            self._prompt.set()

    async def start(self):
        await self.c.start_notify(self._notify, self._on_notify)
        await asyncio.sleep(0.3)

    async def _write(self, text: str):
        await self.c.write_gatt_char(self._write_char, text.encode(), response=False)

    def _lines(self) -> list[str]:
        raw = bytes(self._buf).decode("ascii", "replace")
        return [l.strip() for l in raw.replace(">", "").replace("\r", "\n").split("\n") if l.strip()]

    async def cmd(self, text: str, timeout: float = 6.0) -> str:
        """Send one line, wait for the '>' prompt, return the reply without the echo."""
        check_command(text, self.raw_frames)
        up = text.strip().upper().replace(" ", "")
        self._buf.clear()
        self._prompt.clear()
        await self._write(text + "\r")
        try:
            await asyncio.wait_for(self._prompt.wait(), timeout)
        except asyncio.TimeoutError:
            pass
        lines = self._lines()
        if lines and lines[0].upper().replace(" ", "") == up:
            lines = lines[1:]
        out = "\n".join(lines)
        if up == "ATCAF0" and "OK" in out:
            self.raw_frames = True
        elif up in ("ATCAF1", "ATZ", "ATD", "ATWS"):
            self.raw_frames = False
        if self.verbose:
            print(f"> {text:<16} -> {out!r}")
        return out

    async def init(self, headers: bool = True):
        """Reset the adapter and put it in a predictable, terse state."""
        await self.cmd("ATZ", timeout=8)
        for c in ("ATE0", "ATL0", "ATS0", "ATH1" if headers else "ATH0"):
            await self.cmd(c)

    async def monitor(self, seconds: float) -> list[str]:
        """Listen to the bus with ATMA. With ATCSM1 the adapter stays silent: no ACKs, no frames."""
        self._buf.clear()
        self._prompt.clear()
        await self._write("ATMA\r")
        await asyncio.sleep(seconds)
        await self._write("\r")            # any character stops monitoring
        try:
            await asyncio.wait_for(self._prompt.wait(), 3)
        except asyncio.TimeoutError:
            pass
        return [l for l in self._lines() if l != "ATMA"]


async def connect(address: str | None = None, name: str | None = None, verbose: bool = True):
    """Find the adapter by address (or CARWHISPERER_ADDR), else by advertised name."""
    address = address or os.environ.get("CARWHISPERER_ADDR")
    name = name or os.environ.get("CARWHISPERER_NAME", DEFAULT_NAME)
    if address:
        dev = await BleakScanner.find_device_by_address(address, timeout=15.0) or address
    else:
        dev = await BleakScanner.find_device_by_name(name, timeout=15.0)
        if dev is None:
            raise SystemExit(f"No BLE device named {name!r} found. Pass --address or set CARWHISPERER_ADDR.")
    client = BleakClient(dev, timeout=20.0)
    await client.connect()
    elm = Elm(client, verbose=verbose)
    await elm.start()
    return client, elm
