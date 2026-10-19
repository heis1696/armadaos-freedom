#!/usr/bin/env python3
# A mirror that drops the connection mid-body ends download_to's read loop
# silently, so only a byte-count check keeps a truncated file from being
# published over a working AppImage. These tests speak raw HTTP on localhost
# to cut the body at an exact offset the way a real dropped connection would.
import getpass
import io
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "decky/armada-store"
WORK = Path(tempfile.mkdtemp(prefix="armada-store-download-test."))
HOME = WORK / "home"
(HOME / "Applications").mkdir(parents=True)

os.environ["DECKY_USER_HOME"] = str(HOME)
os.environ["DECKY_USER"] = getpass.getuser()
os.environ["DECKY_PLUGIN_DIR"] = str(STORE)
os.environ["ARMADA_STORE_STATE_DIR"] = str(WORK / "state")
# The localhost origins below are fixtures, the same trusted class as the
# file:// URLs this escape hatch was added for.
os.environ["ARMADA_STORE_ALLOW_INSECURE_URLS"] = "1"
os.environ["no_proxy"] = "*"
os.environ["NO_PROXY"] = "*"

sys.path.insert(0, str(STORE / "py_modules"))
from armada_store import catalog, installers, jobs

# Spans two read() calls at DOWNLOAD_CHUNK, so the loop runs more than once.
BODY = bytes(range(256)) * 1200
SENT = BODY[:150000]


class RawOrigin:
    """Serves one canned byte stream on 127.0.0.1, then closes."""

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        self._server = socket.socket()
        self._server.settimeout(10)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self.port = self._server.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self

    def _serve(self):
        try:
            conn, _ = self._server.accept()
        except OSError:
            return
        try:
            conn.recv(65536)  # the request line itself does not matter
            conn.sendall(self.payload)
        except OSError:
            pass
        finally:
            conn.close()
            self._server.close()

    def __exit__(self, *exc):
        self._thread.join(timeout=10)
        return False

    def url(self):
        return "http://127.0.0.1:{}/download".format(self.port)


def response(head_lines, body):
    head = "\r\n".join(["HTTP/1.1 200 OK", *head_lines, "Connection: close"])
    return (head + "\r\n\r\n").encode("ascii") + body


class DownloadToTest(unittest.TestCase):
    def download(self, origin, cancel=None):
        sink = io.BytesIO()
        events = []
        installers.download_to(sink, origin.url(), cancel or threading.Event(),
                               lambda done, total: events.append((done, total)))
        return sink, events

    def test_full_response(self):
        declared = len(BODY)
        with RawOrigin(response(["Content-Length: %d" % declared], BODY)) as origin:
            sink, events = self.download(origin)
        self.assertEqual(sink.getvalue(), BODY)
        self.assertEqual(events[-1], (declared, declared))
        dones = [done for done, _ in events]
        self.assertEqual(dones, sorted(dones))
        self.assertGreater(len(events), 1, "chunked reads were not exercised")

    def test_truncated_response_fails(self):
        declared = len(BODY)
        with RawOrigin(response(["Content-Length: %d" % declared], SENT)) as origin:
            with self.assertRaises(installers.TruncatedDownload) as caught:
                self.download(origin)
        self.assertEqual(caught.exception.received, len(SENT))
        self.assertEqual(caught.exception.expected, declared)

    def test_truncated_error_renders_as_text(self):
        # jobs reports failures as str(error), so an exception whose text
        # chokes on integer counts would crash the error path itself.
        error = installers.TruncatedDownload(150000, 307200)
        self.assertIn("150000", str(error))
        self.assertIn("307200", str(error))
        self.assertIn("TruncatedDownload", repr(error))
        self.assertIn("150000", repr(error))

    def test_undeclared_length_succeeds(self):
        # Lengthless bodies (read to EOF) stay a success: nothing to check.
        with RawOrigin(response([], BODY)) as origin:
            sink, events = self.download(origin)
        self.assertEqual(sink.getvalue(), BODY)
        self.assertEqual(events[-1], (len(BODY), 0))
        self.assertTrue(all(total == 0 for _, total in events))

    def test_cancel_mid_download(self):
        cancel = threading.Event()

        def progress(done, total):
            if done:
                cancel.set()

        with RawOrigin(response(["Content-Length: %d" % len(BODY)], BODY)) as origin:
            sink = io.BytesIO()
            with self.assertRaises(installers.Cancelled):
                installers.download_to(sink, origin.url(), cancel, progress)
        self.assertLess(sink.tell(), len(BODY))


class InstallAppimageTest(unittest.TestCase):
    OLD = b"#!/bin/sh\necho previous-install\n"

    def setUp(self):
        self.target = HOME / "Applications" / "Tool.AppImage"
        self.target.write_bytes(self.OLD)
        self.target.chmod(0o755)

    def tearDown(self):
        self.target.unlink(missing_ok=True)
        leftovers = [p.name for p in HOME.iterdir() if p.name.startswith(".armada-store-")]
        self.assertEqual(leftovers, [], "staging directory leaked")

    def install(self, origin, cancel=None, progress=None):
        return installers.install_appimage(
            {"filename": "Tool.AppImage", "url": origin.url()},
            cancel or threading.Event(), progress or (lambda done, total: None))

    def test_truncated_failure_keeps_previous_appimage(self):
        with RawOrigin(response(["Content-Length: %d" % len(BODY)], SENT)) as origin:
            with self.assertRaises(installers.TruncatedDownload):
                self.install(origin)
        self.assertEqual(self.target.read_bytes(), self.OLD)
        self.assertTrue(os.access(self.target, os.X_OK), "previous AppImage lost its exec bit")

    def test_cancel_keeps_previous_appimage(self):
        cancel = threading.Event()

        def progress(done, total):
            cancel.set()

        with RawOrigin(response(["Content-Length: %d" % len(BODY)], BODY)) as origin:
            with self.assertRaises(installers.Cancelled):
                self.install(origin, cancel, progress)
        self.assertEqual(self.target.read_bytes(), self.OLD)

    def test_full_response_replaces_appimage(self):
        # The success path must still commit, or the guard above would be
        # trivially passing against an installer that never publishes.
        with RawOrigin(response(["Content-Length: %d" % len(BODY)], BODY)) as origin:
            filename, tag, stamp = self.install(origin)
        self.assertEqual(filename, "Tool.AppImage")
        self.assertEqual(self.target.read_bytes(), BODY)
        self.assertTrue(os.access(self.target, os.X_OK))


class JobQueueTest(unittest.TestCase):
    """A failed install must land in job error text and the worker must move
    on: an exception that crashes str() would kill the worker thread and
    strand every job queued behind the failed one."""

    def setUp(self):
        with jobs._lock:
            jobs._jobs.clear()
            jobs._queue.clear()
            jobs._worker = None
        self._install_appimage = installers.install_appimage
        self._fetch_icon = installers._fetch_icon

    def tearDown(self):
        installers.install_appimage = self._install_appimage
        installers._fetch_icon = self._fetch_icon

    def settle(self, app_ids, timeout=10.0):
        deadline = time.monotonic() + timeout
        statuses = {}
        while time.monotonic() < deadline:
            statuses = {s["appId"]: s for s in jobs.status()}
            if all(a in statuses and statuses[a]["phase"] not in jobs.ACTIVE_PHASES
                   for a in app_ids):
                return statuses
            time.sleep(0.02)
        self.fail("jobs never settled: " + repr(statuses))

    def test_failed_install_records_text_and_queue_continues(self):
        apps = [a for a in catalog.all_apps()
                if a["install"]["type"] == "appimage" and not a.get("postInstall")]
        failing, succeeding = apps[0], apps[1]

        def fake_install(install, cancel, progress):
            if install["filename"] == failing["install"]["filename"]:
                raise installers.TruncatedDownload(150000, 307200)
            return succeeding["install"]["filename"], "v1", ""

        installers.install_appimage = fake_install
        # Icon URLs in the catalog would hit the network; the desktop entry
        # is not this test's subject.
        installers._fetch_icon = lambda app_id, url: ""

        jobs.start(failing["id"], "install")
        jobs.start(succeeding["id"], "install")
        statuses = self.settle([failing["id"], succeeding["id"]])

        self.assertEqual(statuses[failing["id"]]["phase"], "error")
        text = statuses[failing["id"]]["error"]
        self.assertIn("150000", text)
        self.assertIn("307200", text)
        self.assertEqual(statuses[succeeding["id"]]["phase"], "done")


def tearDownModule():
    shutil.rmtree(WORK, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
