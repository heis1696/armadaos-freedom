#!/usr/bin/env python3
"""Identity collection tests: fake adb only; never connect to a real device."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/diagnostics/collect_android_identity.py"
spec = importlib.util.spec_from_file_location("android_identity", SCRIPT)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
SERIAL = "PRIVATE_CONNECTION_ID_123"


class FakeAdb:
    def __init__(self, listing=None, values=None):
        self.listing = listing if listing is not None else f"List of devices attached\n{SERIAL}\tdevice\n"
        self.values = {
            "ro.product.model": "TB324ZC",
            "ro.product.device": "wuji",
            "ro.build.version.incremental": "TEST_VERSION",
            "ro.boot.flash.locked": "1",
            "kernel_release": "6.12.38-fixture",
            **(values or {}),
        }
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        if args[1:] == ["devices"]:
            return subprocess.CompletedProcess(args, 0, self.listing, "")
        self.assert_readonly(args)
        key = args[-1] if args[-2] == "getprop" else "kernel_release"
        value = self.values.get(key, "")
        if isinstance(value, Exception):
            raise value
        if isinstance(value, tuple):
            return subprocess.CompletedProcess(args, value[0], value[1], SERIAL + " permission denied")
        return subprocess.CompletedProcess(args, 0, value + "\n", "")

    @staticmethod
    def assert_readonly(args):
        if args[1:2] != ["-s"] or args[3:4] != ["shell"]:
            raise AssertionError("unexpected adb invocation")
        allowed = [["getprop", key] for key in collector.PROPERTIES] + [["uname", "-r"]]
        if args[4:] not in allowed:
            raise AssertionError("non-allowlisted device command")


class IdentityTests(unittest.TestCase):
    def test_stock_device_reports_facts_without_connection_identifier(self):
        adb = FakeAdb()
        report = collector.collect(run=adb)
        self.assertEqual(report["target_match"], "matched")
        self.assertEqual(report["fields"]["ro.boot.flash.locked"], {"status": "reported", "value": "1"})
        self.assertEqual(report["fields"]["ro.product.board"]["status"], "unknown")
        self.assertNotIn(SERIAL, json.dumps(report))
        self.assertEqual(len(adb.calls), len(collector.PROPERTIES) + 2)
        forbidden = {"su", "root", "reboot", "setprop", "settings", "dumpsys", "logcat", "install"}
        self.assertFalse(any(forbidden.intersection(call) for call in adb.calls))
        queried_properties = {call[-1] for call in adb.calls if "getprop" in call}
        self.assertFalse(queried_properties.intersection({
            "ro.serialno", "ro.boot.serialno", "ril.serialnumber", "persist.radio.imei",
        }))
        self.assertTrue(all(len(call) == 6 for call in adb.calls[1:]))

    def test_unready_devices_fail_before_queries_without_leaking_identifier(self):
        cases = {
            "no_device": "List of devices attached\n",
            "unauthorized": f"List of devices attached\n{SERIAL}\tunauthorized\n",
            "offline": f"List of devices attached\n{SERIAL}\toffline\n",
            "multiple_devices": f"List of devices attached\n{SERIAL}\tdevice\nSECOND_PRIVATE_ID\tdevice\n",
            "invalid_device_list": f"unexpected output containing {SERIAL}",
        }
        for code, listing in cases.items():
            with self.subTest(code=code):
                adb = FakeAdb(listing)
                with self.assertRaises(collector.CollectionError) as caught:
                    collector.collect(run=adb)
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn(SERIAL, str(caught.exception))
                self.assertEqual(len(adb.calls), 1)

    def test_explicit_selection_is_only_used_for_adb_targeting(self):
        adb = FakeAdb(f"List of devices attached\n{SERIAL}\tdevice\nOTHER_PRIVATE_ID\tdevice\n")
        report = collector.collect(serial=SERIAL, run=adb)
        self.assertTrue(all(call[2] == SERIAL for call in adb.calls[1:]))
        self.assertNotIn(SERIAL, json.dumps(report))
        with self.assertRaisesRegex(collector.CollectionError, "not found"):
            collector.collect(serial="NOT_PRESENT", run=adb)

    def test_property_failures_remain_unknown(self):
        adb = FakeAdb(values={
            "ro.product.board": (1, ""),
            "ro.soc.model": subprocess.TimeoutExpired(["adb", SERIAL], 1),
            "ro.boot.vbmeta.device_state": "Permission denied",
            "ro.build.display.id": "bad\nmultiline",
        })
        report = collector.collect(run=adb)
        for prop in ("ro.product.board", "ro.soc.model", "ro.boot.vbmeta.device_state", "ro.build.display.id"):
            self.assertEqual(report["fields"][prop]["status"], "unknown")
        self.assertNotIn(SERIAL, json.dumps(report))

    def test_echoed_connection_identifier_is_redacted(self):
        report = collector.collect(run=FakeAdb(values={"ro.product.board": "board-" + SERIAL}))
        self.assertNotIn(SERIAL, json.dumps(report))
        self.assertIn("[redacted]", report["fields"]["ro.product.board"]["value"])

    def test_other_and_unknown_models_do_not_claim_support(self):
        for model, device, expected in (("TB323FU", "baldur", "not_matched"),
                                        ("TB324ZC2", "wuji2", "not_matched"),
                                        ("", "", "unknown")):
            with self.subTest(model=model):
                report = collector.collect(run=FakeAdb(values={"ro.product.model": model, "ro.product.device": device}))
                self.assertEqual(report["target_match"], expected)
                self.assertNotIn("supported", report)

    def test_adb_failures_have_sanitized_messages(self):
        for failure, code in ((OSError(SERIAL), "adb_unavailable"),
                              (subprocess.TimeoutExpired(["adb", SERIAL], 1), "timeout")):
            with self.subTest(code=code), patch.object(collector.subprocess, "run", side_effect=failure):
                with self.assertRaises(collector.CollectionError) as caught:
                    collector.collect()
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn(SERIAL, str(caught.exception))

    def test_cli_writes_json_and_never_overwrites_an_existing_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.json"
            with patch.object(collector.subprocess, "run", FakeAdb()), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(collector.main(["--output", str(output)]), 0)
            original = output.read_bytes()
            self.assertEqual(json.loads(original)["expected_model"], "TB324ZC")
            with patch.object(collector.subprocess, "run", FakeAdb()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(collector.main(["--output", str(output)]), 2)
            self.assertEqual(output.read_bytes(), original)

    def test_reports_cannot_be_saved_into_the_repository(self):
        with self.assertRaises(collector.CollectionError) as caught:
            collector.save_report({}, ROOT / "identity-should-not-exist.json")
        self.assertEqual(caught.exception.code, "output_in_repository")
        self.assertFalse((ROOT / "identity-should-not-exist.json").exists())

    def test_cli_does_not_relay_raw_adb_errors(self):
        output, errors = io.StringIO(), io.StringIO()
        result = subprocess.CompletedProcess(["adb", "devices"], 1, SERIAL, SERIAL + " sensitive error")
        with patch.object(collector.subprocess, "run", return_value=result), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            self.assertEqual(collector.main([]), 2)
        self.assertNotIn(SERIAL, output.getvalue() + errors.getvalue())
        self.assertIn("adb_failed", errors.getvalue())

    def test_invalid_timeout_does_not_contact_adb(self):
        with patch.object(collector.subprocess, "run") as run, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                collector.main(["--timeout", "0"])
        self.assertEqual(caught.exception.code, 2)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
