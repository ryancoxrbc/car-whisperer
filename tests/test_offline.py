"""Tests that need no hardware: the safety whitelist, ISO-TP reassembly, decoding, analysis."""
import asyncio
import pathlib
import unittest

from carwhisperer import analyze, fiat
from carwhisperer.safety import Refused, check_command
from carwhisperer.uds import Uds, describe, parse_frames, reassemble

EXAMPLE = pathlib.Path(__file__).parent.parent / "examples" / "idle_rpm_frames.json"


class Whitelist(unittest.TestCase):
    def test_reads_allowed_in_raw_mode(self):
        for c in ("023E00", "0322F190", "031902FF", "021003", "021001", "300000", "ATSP7", "ATPPS", "ATMA"):
            check_command(c, raw_frames=True)

    def test_writes_refused_in_raw_mode(self):
        for c in ("0414FFFFFF",      # ClearDiagnosticInformation
                  "042EF19000",      # WriteDataByIdentifier
                  "021002",          # programming session
                  "022701",          # SecurityAccess
                  "021101",          # ECUReset
                  "0431010203",      # RoutineControl
                  "042F100003",      # InputOutputControl
                  "041003",          # length nibble does not match
                  "1014",            # first frame: multi-frame requests are never sent
                  "ATPP2CSV81", "ATPP2CON", "ATCSM0", "ATSD55"):
            with self.assertRaises(Refused, msg=c):
                check_command(c, raw_frames=True)

    def test_formatted_mode(self):
        for c in ("0100", "03", "07", "0902", "1A80", "22F190", "1081"):
            check_command(c, raw_frames=False)
        for c in ("04", "14FFFFFF", "2EF190", "0800", "3101", "1002", "2701"):
            with self.assertRaises(Refused, msg=c):
                check_command(c, raw_frames=False)


class IsoTp(unittest.TestCase):
    RX = "18DAF110"

    def test_single_frame(self):
        frames = parse_frames("18DAF110027E00", self.RX)
        self.assertEqual(reassemble(frames), (bytes.fromhex("7E00"), True))

    def test_multi_frame(self):
        resp = "18DAF110100B62F1964142\n18DAF11021434445464700"
        data, complete = reassemble(parse_frames(resp, self.RX))
        self.assertTrue(complete)
        self.assertEqual(data, bytes.fromhex("62F196") + b"ABCDEFG\x00")

    def test_truncated_multi_frame(self):
        data, complete = reassemble(parse_frames("18DAF110101462F190202020", self.RX))
        self.assertFalse(complete)
        self.assertEqual(data, bytes.fromhex("62F190202020"))

    def test_other_ids_and_status_words_ignored(self):
        self.assertEqual(parse_frames("NO DATA\n18DAF140027E00\nSTOPPED", self.RX), [])

    def test_request_through_fake_adapter(self):
        class FakeElm:
            verbose = False
            raw_frames = True
            def __init__(self): self.sent = []
            async def cmd(self, text, timeout=0):
                check_command(text, self.raw_frames)
                self.sent.append(text)
                return {"0322F196": "18DAF110100B62F1964142\n18DAF11021434445464700",
                        "0322F188": "18DAF110037F2231"}.get(text, "OK")
        elm = FakeElm()
        u = Uds(elm)
        self.assertEqual(asyncio.run(u.read_did(0xF196))[3:10], b"ABCDEFG")
        self.assertIn("requestOutOfRange", describe(asyncio.run(u.read_did(0xF188))))
        with self.assertRaises(Refused):
            asyncio.run(u.request(bytes.fromhex("14FFFFFF")))
        self.assertNotIn("0414FFFFFF", elm.sent)


class Decoding(unittest.TestCase):
    def test_dtc(self):
        codes = fiat.decode_dtcs(bytes.fromhex("5902CF01351408"))
        self.assertEqual(codes, [("P0135-14", 0x08, ["confirmedDTC"])])
        self.assertEqual(fiat.decode_dtcs(bytes.fromhex("5902CF")), [])

    def test_rpm_frame(self):
        self.assertEqual(fiat.rpm_from_frame(bytes.fromhex("001102CA131A7300")), 714)


class Analysis(unittest.TestCase):
    def test_example_capture(self):
        bursts = analyze.load_bursts(EXAMPLE)
        s = analyze.summary(bursts)
        self.assertEqual((s["min"], s["max"]), (700, 730))
        self.assertAlmostEqual(s["mean"], 715.7, places=1)
        o = analyze.engine_orders(bursts)
        self.assertGreater(o["half_order_peak"], 5 * o["background_3_to_9hz"])


class FakeCar:
    """Stands in for the adapter and car, replaying replies seen in the real session."""
    REPLIES = {
        "023E00": "18DAF110027E00",
        "0322F196": "18DAF110100962F196355346\n18DAF1102139414700",
        "0322F187": "18DAF110037F2231",
        "03190208": "18DAF110075902CF01351408",
        "03190204": "18DAF110035902CF",
        "03190201": "18DAF110035902CF",
        "03221000": "18DAF110056210000B34",
        "03221003": "18DAF11005621003" + "0086",
        "03221004": "18DAF11005621004" + "008E",
    }

    def __init__(self):
        self.verbose, self.raw_frames, self.sent, self.target = False, False, [], "10"

    async def init(self, headers=True):
        pass

    async def cmd(self, text, timeout=0):
        check_command(text, self.raw_frames)
        self.sent.append(text)
        if text == "ATCAF0":
            self.raw_frames = True
        if text.startswith("ATSHDA"):
            self.target = text[6:8]
        if text.startswith("AT"):
            return "OK"
        return self.REPLIES.get(text, "NO DATA") if self.target == "10" else "NO DATA"

    async def monitor(self, seconds):
        return ["0618A001001102CA131A7300", "0618A001001102CD131A7300", "0A18A0010100808400DA1600", "BUFFER FULL"]


class CliSmoke(unittest.TestCase):
    def run_cmd(self, name, **kw):
        import argparse, contextlib, io
        from carwhisperer import cli
        car, out = FakeCar(), io.StringIO()
        with contextlib.redirect_stdout(out):
            asyncio.run(getattr(cli, "cmd_" + name)(car, argparse.Namespace(**kw)))
        return car, out.getvalue()

    def test_scan_finds_only_the_engine(self):
        _, out = self.run_cmd("scan")
        self.assertIn("0x10 answers", out)
        self.assertIn("1 modules", out)

    def test_ident_and_dtc_and_live(self):
        _, out = self.run_cmd("ident", target=0x10, show_private=False)
        self.assertIn("5SF9AG", out)
        self.assertIn("requestOutOfRange", out)
        _, out = self.run_cmd("dtc", target=0x10, all=False)
        self.assertIn("P0135-14", out)
        _, out = self.run_cmd("live", seconds=0.05)
        self.assertIn("engine speed 717 rpm", out)
        self.assertIn("battery voltage 14.2 V", out)

    def test_sweep_and_sniff_and_capture(self):
        import os, tempfile
        _, out = self.run_cmd("sweep", target=0x10, start=0x1000, end=0x1004)
        self.assertIn("3 DIDs answered", out)
        _, out = self.run_cmd("sniff", seconds=1.5, bits=29)
        self.assertIn("0618A001", out)
        path = os.path.join(tempfile.mkdtemp(), "c.json")
        car, _ = self.run_cmd("capture", id="0618A001", seconds=0, bursts=2, out=path)
        self.assertEqual(analyze.load_bursts(path), [[714, 717], [714, 717]])
        self.assertTrue(all(c.startswith("AT") for c in car.sent), "capture must not transmit requests")

    def test_no_command_sends_a_forbidden_service(self):
        for name, kw in (("scan", {}), ("ident", dict(target=0x10, show_private=True)), ("dtc", dict(target=0x10, all=True))):
            car, _ = self.run_cmd(name, **kw)
            services = {c[2:4] for c in car.sent if not c.startswith("AT") and not c.startswith("30")}
            self.assertLessEqual(services, {"3E", "22", "19"})


if __name__ == "__main__":
    unittest.main()
