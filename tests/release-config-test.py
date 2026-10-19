#!/usr/bin/env python3
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "system_files/usr/lib/armada"
sys.path.insert(0, str(LIB))
import release_config


class ReleaseConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.path = self.directory / "release.json"
        self.valid = json.loads(
            (ROOT / "system_files/usr/share/armada/release.json").read_text()
        )

    def write(self, data):
        self.path.write_text(json.dumps(data))
        return self.path

    def assert_invalid(self, data):
        with self.assertRaises(release_config.ReleaseConfigError):
            release_config.load_release_config(self.write(data))

    def test_repository_release_json_is_valid(self):
        config = release_config.load_release_config(
            ROOT / "system_files/usr/share/armada/release.json"
        )
        self.assertEqual(config.schema_version, 1)
        self.assertEqual(config.image_repository, "ghcr.io/heis1696/armadaos-freedom")
        self.assertEqual(config.channels, ("stable", "beta", "testing"))
        self.assertEqual(config.public_key_path, "/etc/pki/containers/freedom.pub")

    def test_missing_and_unreadable_files_are_rejected(self):
        with self.assertRaises(release_config.ReleaseConfigError):
            release_config.load_release_config(self.directory / "missing.json")
        self.path.mkdir()
        with self.assertRaises(release_config.ReleaseConfigError):
            release_config.load_release_config(self.path)

    def test_malformed_json_and_non_object_roots_are_rejected(self):
        self.path.write_text("{")
        with self.assertRaises(release_config.ReleaseConfigError):
            release_config.load_release_config(self.path)
        self.assert_invalid([])

    def test_duplicate_unknown_and_missing_fields_are_rejected(self):
        self.path.write_text(
            '{"schema_version":1,"schema_version":1,'
            '"image_repository":"ghcr.io/heis1696/armadaos-freedom",'
            '"channels":["stable"],"public_key_path":"/key.pub"}'
        )
        with self.assertRaises(release_config.ReleaseConfigError):
            release_config.load_release_config(self.path)
        data = dict(self.valid)
        del data["public_key_path"]
        self.assert_invalid(data)
        data = dict(self.valid)
        data["repository"] = data.pop("image_repository")
        self.assert_invalid(data)

    def test_schema_version_must_be_the_integer_one(self):
        for version in (0, 2, "1", True, 1.0, None):
            data = dict(self.valid)
            data["schema_version"] = version
            with self.subTest(version=version):
                self.assert_invalid(data)

    def test_repository_must_be_a_bare_lowercase_registry_repository(self):
        for repository in (
            "ghcr.io/Heis1696/ArmadaOS",
            "ghcr.io/heis1696/armadaos-freedom:stable",
            "ghcr.io/heis1696/armadaos-freedom@sha256:deadbeef",
            "ghcr.io/heis1696/armadaos-freedom@sha256:" + "0123456789abcdef" * 4,
            "docker://ghcr.io/heis1696/armadaos-freedom",
            "containers-storage:localhost/armada:latest",
            "armadaos-freedom",
            "ghcr.io//armadaos-freedom",
            "ghcr.io/heis1696/armada os",
            "",
            None,
        ):
            data = dict(self.valid)
            data["image_repository"] = repository
            with self.subTest(repository=repository):
                self.assert_invalid(data)

    def test_image_reference_parser_accepts_only_supported_forms(self):
        digest = "sha256:" + "0123456789abcdef" * 4
        valid = (
            ("ostree-image-signed:docker://ghcr.io/heis1696/armadaos-freedom:stable",
             "ghcr.io/heis1696/armadaos-freedom", "stable", None),
            (f"ostree-image-signed:docker://ghcr.io/heis1696/armadaos-freedom@{digest}",
             "ghcr.io/heis1696/armadaos-freedom", None, digest),
            (f"ostree-image-signed:docker://ghcr.io/heis1696/armadaos-freedom:stable@{digest}",
             "ghcr.io/heis1696/armadaos-freedom", "stable", digest),
            ("ostree-unverified-registry:localhost:5000/armada:feature-a",
             "localhost:5000/armada", "feature-a", None),
            ("ostree-unverified-image:docker://local.armadaos.dev/armada:feature-a",
             "local.armadaos.dev/armada", "feature-a", None),
            ("docker://ghcr.io/armada-os/armada:testing",
             "ghcr.io/armada-os/armada", "testing", None),
            ("ostree-unverified-registry:example.invalid/ghcr.io/virtudude/armada:RC_1.0",
             "example.invalid/ghcr.io/virtudude/armada", "RC_1.0", None),
        )
        for reference, repository, tag, digest_value in valid:
            with self.subTest(reference=reference):
                parsed = release_config.parse_image_reference(reference)
                self.assertEqual(parsed.repository, repository)
                self.assertEqual(parsed.tag, tag)
                self.assertEqual(parsed.digest, digest_value)

    def test_image_reference_parser_rejects_nested_and_malformed_values(self):
        digest = "sha256:" + "0123456789abcdef" * 4
        invalid = (
            "containers-storage:docker://ghcr.io/heis1696/armadaos-freedom:stable",
            "garbage:docker://ghcr.io/heis1696/armadaos-freedom:beta",
            "ostree-unverified-registry:docker://ghcr.io/heis1696/armadaos-freedom:stable",
            "ostree-image-signed:http://ghcr.io/heis1696/armadaos-freedom:stable",
            "ostree-image-signed:docker://containers-storage:localhost/armada:latest",
            "ostree-unverified-registry:containers-storage:localhost/armada:latest",
            "ostree-unverified-registry:dir:/tmp/armada:latest",
            "ostree-unverified-registry:oci:archive/armada:latest",
            "ostree-unverified-registry:",
            "ostree-image-signed:",
            "docker://",
            "",
            None,
            "ghcr.io/heis1696/armadaos-freedom:stable",
            "http://ghcr.io/heis1696/armadaos-freedom:stable",
            "ostree-unverified-registry:ghcr.io/heis1696/armadaos-freedom:",
            "ostree-unverified-registry:ghcr.io/heis1696/armadaos-freedom:-bad",
            "ostree-unverified-registry:ghcr.io/heis1696/armadaos-freedom:bad tag",
            "ostree-unverified-registry:ghcr.io/heis1696/armadaos-freedom:bad/tag",
            "ostree-unverified-registry:ghcr.io/heis1696/armadaos-freedom:"
            + "t" * 129,
            "ostree-unverified-registry:ghcr.io/heis1696/armadaos-freedom@sha256:deadbeef",
            "ostree-unverified-registry:ghcr.io/heis1696/armadaos-freedom@md5:" + "a" * 32,
            "ostree-unverified-registry:ghcr.io/heis1696/armadaos-freedom@sha256:"
            + "A" * 64,
            "ostree-unverified-registry:ghcr.io/heis1696/armadaos-freedom@sha256:"
            + "a" * 63,
            f"ostree-unverified-registry:ghcr.io/heis1696/armadaos-freedom@{digest}@{digest}",
            "ostree-unverified-registry:GHCR.IO/heis1696/armadaos-freedom:stable",
            "ostree-unverified-registry:ghcr.io//armadaos-freedom",
            "ostree-unverified-registry:ghcr.io/heis1696/../armadaos-freedom",
            "ostree-unverified-registry:ghcr.io/heis1696/",
            "ostree-unverified-registry:armadaos-freedom",
        )
        for reference in invalid:
            with self.subTest(reference=reference):
                with self.assertRaises(release_config.ReleaseConfigError):
                    release_config.parse_image_reference(reference)

    def test_channels_must_be_a_nonempty_known_unique_list(self):
        for channels in (
            [],
            "stable",
            ["stable", "stable"],
            ["canary"],
            ["stable", "../testing"],
            [""],
            [None],
        ):
            data = dict(self.valid)
            data["channels"] = channels
            with self.subTest(channels=channels):
                self.assert_invalid(data)

    def test_public_key_path_must_be_absolute_and_simple(self):
        for key_path in (
            "etc/pki/containers/freedom.pub",
            "/etc/pki/containers/../secret",
            "/etc/pki/containers/",
            "/",
            "/etc/pki/containers/freedom pub",
            None,
        ):
            data = dict(self.valid)
            data["public_key_path"] = key_path
            with self.subTest(key_path=key_path):
                self.assert_invalid(data)

    def test_cli_prints_repository_and_channels_or_fails(self):
        path = self.write(self.valid)
        result = subprocess.run(
            [sys.executable, str(LIB / "release_config.py"), "--config", str(path)],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "ghcr.io/heis1696/armadaos-freedom\tstable beta testing\n",
        )
        result = subprocess.run(
            [sys.executable, str(LIB / "release_config.py"), "--config", str(self.directory / "missing")],
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("armada-release-config:", result.stderr)

        result = subprocess.run(
            [sys.executable, str(LIB / "release_config.py"), "--reference",
             "ostree-unverified-registry:ghcr.io/heis1696/armadaos-freedom:beta"],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "ghcr.io/heis1696/armadaos-freedom\n")
        result = subprocess.run(
            [sys.executable, str(LIB / "release_config.py"), "--reference",
             "containers-storage:docker://ghcr.io/heis1696/armadaos-freedom:stable"],
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("armada-release-config:", result.stderr)


if __name__ == "__main__":
    unittest.main()
