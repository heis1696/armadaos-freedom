#!/usr/bin/env python3
"""Collect a small, read-only Android identity report using an existing adb."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[2]
PROPERTIES = (
    "ro.product.model",
    "ro.product.device",
    "ro.product.board",
    "ro.soc.model",
    "ro.build.display.id",
    "ro.build.fingerprint",
    "ro.build.version.incremental",
    "ro.build.version.release",
    "ro.build.version.security_patch",
    "ro.boot.flash.locked",
    "ro.boot.vbmeta.device_state",
    "ro.boot.verifiedbootstate",
    "ro.boot.slot_suffix",
    "ro.bootloader",
)
TARGET = re.compile(r"(?<![A-Z0-9])TB324ZC(?![A-Z0-9])", re.IGNORECASE)
ERRORS = {
    "adb_unavailable": "Cannot run adb; specify its executable with --adb.",
    "adb_failed": "ADB failed; its raw output was omitted to protect device identifiers.",
    "timeout": "ADB timed out. No device state was changed.",
    "invalid_device_list": "ADB returned an unrecognized device list.",
    "no_device": "No device is connected. Connect the tablet and authorize USB debugging.",
    "multiple_devices": "Multiple devices are connected. Connect only the target tablet, or use --serial.",
    "device_not_found": "The selected device was not found.",
    "unauthorized": "Authorize USB debugging on the tablet, then retry.",
    "offline": "The selected device is offline.",
    "device_not_ready": "The selected device is not in an authorized Android ADB session.",
    "output_in_repository": "Save the report outside the repository.",
}


class CollectionError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(ERRORS[code])


def invoke(run, arguments, timeout):
    try:
        return run(arguments, capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise CollectionError("timeout") from None
    except OSError:
        raise CollectionError("adb_unavailable") from None


def choose_device(output, requested=None):
    lines = output.strip().splitlines()
    if not lines or lines[0].strip() != "List of devices attached":
        raise CollectionError("invalid_device_list")
    devices = []
    for line in lines[1:]:
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 2:
            raise CollectionError("invalid_device_list")
        devices.append(tuple(fields))
    if requested is not None:
        devices = [item for item in devices if item[0] == requested]
        if not devices:
            raise CollectionError("device_not_found")
    if not devices:
        raise CollectionError("no_device")
    if len(devices) != 1:
        raise CollectionError("multiple_devices")
    serial, state = devices[0]
    if state != "device":
        raise CollectionError(state if state in ("unauthorized", "offline") else "device_not_ready")
    return serial


def read_value(run, adb, serial, command, timeout):
    try:
        response = invoke(run, [adb, "-s", serial, "shell", *command], timeout)
    except CollectionError as error:
        return {"status": "unknown", "reason": error.code}
    if response.returncode:
        return {"status": "unknown", "reason": "query_failed"}
    value = response.stdout.strip()
    if not value:
        return {"status": "unknown", "reason": "empty"}
    if len(value) > 512 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return {"status": "unknown", "reason": "invalid_response"}
    if "permission denied" in value.lower():
        return {"status": "unknown", "reason": "permission_denied"}
    # The connection identifier is needed in memory to select adb's target,
    # but is never persisted, even if a broken property echoes it back.
    return {"status": "reported", "value": value.replace(serial, "[redacted]")}


def collect(adb="adb", serial=None, timeout=10, run=None):
    run = run or subprocess.run
    listing = invoke(run, [adb, "devices"], timeout)
    if listing.returncode:
        raise CollectionError("adb_failed")
    selected = choose_device(listing.stdout, serial)
    fields = {prop: read_value(run, adb, selected, ["getprop", prop], timeout)
              for prop in PROPERTIES}
    fields["kernel_release"] = read_value(run, adb, selected, ["uname", "-r"], timeout)
    identities = [fields[key].get("value") for key in ("ro.product.model", "ro.product.device")]
    match = any(TARGET.search(value) for value in identities if value)
    target_status = "matched" if match else ("not_matched" if any(identities) else "unknown")
    return {
        "schema_version": 1,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "expected_model": "TB324ZC",
        "target_match": target_status,
        "fields": fields,
        "notes": [
            "Boot flags are Android-reported values, not independent proof of bootloader state.",
            "This report does not establish Linux support or authorize flashing.",
        ],
    }


def save_report(report, output=None):
    if output is None:
        destination = Path(tempfile.mkdtemp(prefix="wuji-identity-")) / "identity.json"
    else:
        destination = Path(output).expanduser().resolve()
    if destination.is_relative_to(REPO_ROOT):
        raise CollectionError("output_in_repository")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb", help="path to the existing adb executable")
    parser.add_argument("--serial", help="select one connection; the identifier is not saved")
    parser.add_argument("--output", help="new JSON file outside the repository; never overwritten")
    parser.add_argument("--timeout", type=float, default=10, help="seconds per ADB command (1..60)")
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 60:
        parser.error("--timeout must be between 1 and 60")
    try:
        report = collect(args.adb, args.serial, args.timeout)
        destination = save_report(report, args.output)
    except CollectionError as error:
        print(f"{error.code}: {error}", file=sys.stderr)
        return 2
    except FileExistsError:
        print("Output already exists; choose a new filename.", file=sys.stderr)
        return 2
    except OSError:
        print("Cannot create the report at the requested location.", file=sys.stderr)
        return 2
    print(f"Report saved: {destination}")
    print(f"Target identity: {report['target_match']}; boot flags are reported values only.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
