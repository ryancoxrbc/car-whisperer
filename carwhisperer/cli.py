"""Command line: python -m carwhisperer <command>. Every command is read-only."""
import argparse
import asyncio
import collections
import json
import time

from . import analyze, fiat
from .elm import connect, is_status
from .uds import Uds, describe, parse_frames, positive


def hexint(s: str) -> int:
    return int(s, 16)


async def cmd_adapter(elm, args):
    """Talk to the adapter only. Nothing is sent to the car."""
    await elm.init()
    for c in ("ATI", "AT@1", "ATRV", "ATDP", "ATPPS"):
        await elm.cmd(c, timeout=8)


async def cmd_obd(elm, args):
    """Try standard OBD-II (Mode 01 PID 00) on each protocol. Expected to fail on this car."""
    await elm.init()
    await elm.cmd("ATRV")
    for proto, name in (("0", "automatic search"), ("6", "CAN 11-bit 500k"), ("7", "CAN 29-bit 500k"),
                        ("5", "KWP2000 fast init"), ("4", "KWP2000 5-baud init"), ("3", "ISO 9141-2")):
        print(f"--- protocol {proto}: {name}")
        await elm.cmd("ATSP" + proto)
        await elm.cmd("0100", timeout=20)
    await elm.cmd("ATSP0")


async def cmd_sniff(elm, args):
    """Listen to the CAN bus without transmitting and list the identifiers seen."""
    await elm.init()
    for c in ("ATCAF0", "ATCSM1", "ATSP7" if args.bits == 29 else "ATSP6"):
        await elm.cmd(c)
    idlen = 8 if args.bits == 29 else 3
    ids, samples = collections.Counter(), collections.defaultdict(set)
    elm.verbose = False
    for _ in range(max(1, round(args.seconds / 1.5))):       # short bursts: the BLE link overflows otherwise
        for line in await elm.monitor(1.5):
            if is_status(line) or len(line) <= idlen:
                continue
            ids[line[:idlen]] += 1
            if len(samples[line[:idlen]]) < 3:
                samples[line[:idlen]].add(line[idlen:])
    print(f"{sum(ids.values())} frames, {len(ids)} identifiers")
    for cid in sorted(ids):
        print(f"  {cid}  x{ids[cid]:<5} {' | '.join(sorted(samples[cid]))}   {fiat.BROADCAST.get(cid, '')}")


async def cmd_scan(elm, args):
    """Send TesterPresent to every address 18DAxxF1 and list the modules that answer."""
    await elm.init()
    u = Uds(elm)
    await u.setup()
    await elm.cmd("ATST19")                                  # 100 ms is enough for a single frame
    elm.verbose = False
    found = []
    for addr in range(256):
        await u.retarget(addr)
        if positive(await u.request(b"\x3E\x00", timeout=2)):
            found.append(addr)
            print(f"  0x{addr:02X} answers   {fiat.MODULES.get(addr, '')}")
    print(f"{len(found)} modules: {[f'0x{a:02X}' for a in found]}")


async def cmd_ident(elm, args):
    """Read the identification DIDs of one module."""
    await elm.init()
    u = Uds(elm, args.target)
    await u.setup()
    for did, name in fiat.IDENT_DIDS.items():
        data = await u.read_did(did)
        if did in fiat.PRIVATE_DIDS and positive(data) and not args.show_private:
            print(f"  {did:04X} {name:<28} ({len(data) - 3} bytes, hidden; use --show-private)")
        else:
            print(f"  {did:04X} {name:<28} {describe(data)}")


async def cmd_dtc(elm, args):
    """Read fault codes with their status. Never clears them."""
    await elm.init()
    u = Uds(elm, args.target)
    await u.setup()
    for mask, label in ((0x08, "confirmed"), (0x04, "pending"), (0x01, "failing now")):
        data = await u.request(bytes([0x19, 0x02, mask]), timeout=6)
        codes = fiat.decode_dtcs(data) if positive(data) else []
        print(f"{label}: {len(codes)}" + ("" if positive(data) else f"   ({describe(data)})"))
        for code, status, flags in codes:
            print(f"  {code}  status {status:02X}  {', '.join(flags)}")
    if args.all:
        data = await u.request(bytes([0x19, 0x02, 0xFF]), timeout=8)
        print("every code the ECU reports, any status:")
        for code, status, flags in fiat.decode_dtcs(data):
            print(f"  {code}  status {status:02X}  {', '.join(flags)}")


async def cmd_live(elm, args):
    """Poll the known live-data DIDs of the engine ECU."""
    await elm.init()
    u = Uds(elm, 0x10)
    await u.setup()
    end = time.time() + args.seconds
    while time.time() < end:
        row = []
        for did, (name, unit, scale, _) in fiat.LIVE_DIDS.items():
            data = await u.read_did(did, timeout=1.5)
            if positive(data):
                row.append(f"{name} {scale(int.from_bytes(data[3:], 'big')):g} {unit}")
        print("  " + " | ".join(row))


async def cmd_sweep(elm, args):
    """Ask for every DID in a range and print the ones that answer."""
    await elm.init()
    u = Uds(elm, args.target)
    await u.setup()
    await elm.cmd("ATST28")
    hits = 0
    for did in range(args.start, args.end + 1):
        data = await u.read_did(did, timeout=1.5)
        if positive(data):
            hits += 1
            print(f"  {did:04X} -> {data[3:].hex().upper()}", flush=True)
    print(f"{hits} DIDs answered in {args.start:04X}-{args.end:04X}")


async def cmd_capture(elm, args):
    """Record one broadcast frame passively and save the raw data bytes as JSON."""
    await elm.init()
    for c in ("ATSP7", "ATCAF0", "ATCSM1", f"ATCF{args.id}", "ATCM1FFFFFFF"):
        await elm.cmd(c)
    elm.verbose = False
    bursts = []
    for i in range(args.bursts):
        frames = parse_frames("\n".join(await elm.monitor(args.seconds)), args.id.upper())
        bursts.append([f.hex().upper() for f in frames])
        print(f"  burst {i + 1}: {len(frames)} frames")
    with open(args.out, "w") as fh:
        json.dump(bursts, fh)
    print(f"saved {args.out}")


def cmd_analyze(args):
    bursts = analyze.load_bursts(args.file)
    s = analyze.summary(bursts)
    print(f"frames {s['frames']}, mean {s['mean']:.1f} rpm, stdev {s['stdev']:.1f}, range {s['min']}-{s['max']}")
    print(f"value changes per second {s['value_changes_per_second']:.1f}, largest drop between frames {s['largest_drop_between_frames']} rpm")
    o = analyze.engine_orders(bursts)
    print(f"crank rotation {o['rotation_hz']:.2f} Hz")
    print(f"  below 2 Hz        ±{o['below_2hz']:.2f} rpm")
    print(f"  half order        ±{o['half_order']:.2f} rpm (peak bin {o['half_order_peak']:.2f}, background {o['background_3_to_9hz']:.2f})")
    print(f"  first order       ±{o['first_order']:.2f} rpm")
    if args.plots:
        analyze.plots(bursts, args.plots)
        print(f"charts written to {args.plots}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="carwhisperer", description=__doc__)
    p.add_argument("--address", help="BLE address of the adapter (or set CARWHISPERER_ADDR)")
    p.add_argument("--name", help="advertised BLE name to look for (default VEEPEAK)")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("adapter", help=cmd_adapter.__doc__)
    sub.add_parser("obd", help=cmd_obd.__doc__)
    s = sub.add_parser("sniff", help=cmd_sniff.__doc__)
    s.add_argument("--seconds", type=float, default=12); s.add_argument("--bits", type=int, choices=(11, 29), default=29)
    sub.add_parser("scan", help=cmd_scan.__doc__)
    s = sub.add_parser("ident", help=cmd_ident.__doc__)
    s.add_argument("--target", type=hexint, default=0x10); s.add_argument("--show-private", action="store_true")
    s = sub.add_parser("dtc", help=cmd_dtc.__doc__)
    s.add_argument("--target", type=hexint, default=0x10); s.add_argument("--all", action="store_true")
    s = sub.add_parser("live", help=cmd_live.__doc__)
    s.add_argument("--seconds", type=float, default=20)
    s = sub.add_parser("sweep", help=cmd_sweep.__doc__)
    s.add_argument("--target", type=hexint, default=0x10); s.add_argument("--start", type=hexint, required=True); s.add_argument("--end", type=hexint, required=True)
    s = sub.add_parser("capture", help=cmd_capture.__doc__)
    s.add_argument("--id", default=fiat.RPM_FRAME); s.add_argument("--seconds", type=float, default=10)
    s.add_argument("--bursts", type=int, default=6); s.add_argument("--out", default="capture.json")
    s = sub.add_parser("analyze", help="Statistics and spectrum of a capture file (no hardware needed)")
    s.add_argument("file"); s.add_argument("--plots", metavar="DIR")
    args = p.parse_args(argv)

    if args.command == "analyze":
        return cmd_analyze(args)

    async def run():
        client, elm = await connect(args.address, args.name)
        try:
            await globals()[f"cmd_{args.command}"](elm, args)
        finally:
            try:
                elm.verbose = False
                await elm.cmd("ATSP0")           # leave the adapter in automatic mode
            finally:
                await client.disconnect()
    asyncio.run(run())
