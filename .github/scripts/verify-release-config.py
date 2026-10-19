#!/usr/bin/env python3
"""Release gate for the fork's signing configuration.

build.yml runs this in a dedicated preflight job that both the packages job
(which pushes package images) and build_push depend on, so every registry
write waits for it; promote.yml runs it before any registry action. It fails
closed unless all of the following hold:

- system_files/usr/share/armada/release.json validates against the same
  runtime schema the device uses (system_files/usr/lib/armada/release_config.py:
  load_release_config), and its image_repository matches the GitHub repository
  the workflow runs in,
- the fork public key (release.json: public_key_path, vendored under
  system_files/) exists and is proven to parse as a public key by openssl —
  never a private one; a missing openssl is a hard failure in release mode,
  and
- the client trust config (containers/policy.json and the sigstore attachment
  registries.d) pins the fork repository to exactly that key and identity
  while keeping the upstream rules intact.

Local development builds and PR builds never invoke this script, so they keep
working without a key. --allow-missing-key downgrades only the key-presence,
key-validity and openssl-availability checks to warnings for local sanity
runs; release workflows must not pass it.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_JSON = "system_files/usr/share/armada/release.json"
POLICY_JSON = "system_files/etc/containers/policy.json"
REGISTRIES_D = "system_files/etc/containers/registries.d/ghcr-armada.yaml"
SYSTEM_FILES_PREFIX = "system_files"

EXPECTED_CHANNELS = ["stable", "beta", "testing"]
EXPECTED_REGISTRY_HOST = "ghcr.io"
RELEASE_CONFIG_HELPER_DIR = "system_files/usr/lib/armada"
RELEASE_CONFIG_HELPER = RELEASE_CONFIG_HELPER_DIR + "/release_config.py"
KEY_PATH_PATTERN = re.compile(r"^/etc/pki/containers/[A-Za-z0-9._-]+\.pub$")
REPOSITORY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$")
IMAGE_REPOSITORY_PATTERN = re.compile(
    r"^ghcr\.io/[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$"
)

# Upstream trust anchors that must survive next to the fork entry: the fork's
# signatures are the only ones that may verify fork images, and the upstream
# keys keep verifying only their own repositories.
EXPECTED_UPSTREAM_RULES = {
    "ghcr.io/armada-os/armada": {
        "keyPaths": [
            "/etc/pki/containers/armada.pub",
            "/etc/pki/containers/armada-backup.pub",
        ],
        "signedIdentity": {"type": "matchRepository"},
    },
    "ghcr.io/virtudude/armada": {
        "keyPaths": [
            "/etc/pki/containers/armada.pub",
            "/etc/pki/containers/armada-backup.pub",
        ],
        "signedIdentity": {
            "type": "exactRepository",
            "dockerRepository": "ghcr.io/armada-os/armada",
        },
    },
}

PEM_PUBLIC_KEY_START = "-----BEGIN PUBLIC KEY-----"
PEM_PUBLIC_KEY_END = "-----END PUBLIC KEY-----"
FORBIDDEN_KEY_MARKERS = ("PRIVATE KEY", "ENCRYPTED")


class Gate:
    def __init__(self, allow_missing_key: bool) -> None:
        self.allow_missing_key = allow_missing_key
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def finish(self) -> int:
        for warning in self.warnings:
            print(f"verify-release-config: warning: {warning}", file=sys.stderr)
        for error in self.errors:
            print(f"verify-release-config: error: {error}", file=sys.stderr)
        if self.errors:
            print(
                "verify-release-config: release config check FAILED "
                f"({len(self.errors)} error(s))",
                file=sys.stderr,
            )
            return 1
        print("verify-release-config: release config check passed")
        return 0


def load_json(gate: Gate, root: Path, rel_path: str, what: str):
    path = root / rel_path
    if not path.is_file():
        gate.error(f"{what} is missing: {rel_path}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        gate.error(f"{what} ({rel_path}) must parse as data: {exc}")
        return None


def load_schema_validator(gate: Gate, root: Path):
    """Import the runtime release-config helper from the tree under check.

    The gate must judge release.json with the same code the device runs, so
    the helper is loaded from ``root`` (not from this script's checkout). Any
    failure to load it is a gate error, never a silent downgrade.
    """
    helper_path = root / RELEASE_CONFIG_HELPER
    if not helper_path.is_file():
        gate.error(f"release config schema helper is missing: {RELEASE_CONFIG_HELPER}")
        return None
    helper_dir = str(root / RELEASE_CONFIG_HELPER_DIR)
    if helper_dir not in sys.path:
        sys.path.insert(0, helper_dir)
    try:
        import release_config
    except Exception as exc:  # any import failure must fail the gate
        gate.error(
            f"release config schema helper ({RELEASE_CONFIG_HELPER}) could not be "
            f"imported: {exc}"
        )
        return None
    return release_config


def check_release_json(gate: Gate, root: Path):
    validator = load_schema_validator(gate, root)
    if validator is None:
        gate.error("cannot validate release metadata schema")
        return None

    path = root / RELEASE_JSON
    if not path.is_file():
        gate.error(f"release metadata is missing: {RELEASE_JSON}")
        return None
    try:
        config = validator.load_release_config(path)
    except validator.ReleaseConfigError as exc:
        gate.error(f"{RELEASE_JSON} failed the runtime release-config schema: {exc}")
        return None

    # The shared schema accepts any registry and any subset of the channel
    # tokens; this fork's release contract is stricter and is enforced here.
    repository = config.image_repository
    if not IMAGE_REPOSITORY_PATTERN.match(repository):
        gate.error(
            f"{RELEASE_JSON}: image_repository must be a plain {EXPECTED_REGISTRY_HOST}/"
            f"owner/name repository without tag, digest, or transport, got {repository!r}"
        )
        repository = None

    if list(config.channels) != EXPECTED_CHANNELS:
        gate.error(
            f"{RELEASE_JSON}: channels must be exactly {EXPECTED_CHANNELS}, got "
            f"{list(config.channels)!r}; channel changes are a release-identity contract change"
        )

    key_path = config.public_key_path
    if not KEY_PATH_PATTERN.match(key_path):
        gate.error(
            f"{RELEASE_JSON}: public_key_path must be an absolute /etc/pki/containers/*.pub "
            f"path, got {key_path!r}"
        )
        key_path = None

    return {
        "image_repository": repository,
        "public_key_path": key_path,
    }


def check_running_repository(gate: Gate, image_repository: str) -> None:
    expected = f"{EXPECTED_REGISTRY_HOST}/{image_repository.split('/', 1)[1]}"
    github_repository = os.environ.get("GITHUB_REPOSITORY", "")
    if not github_repository:
        gate.warn(
            "GITHUB_REPOSITORY is not set; skipping the workflow-repository "
            "identity check (local run)"
        )
        return
    actual = f"{EXPECTED_REGISTRY_HOST}/{github_repository.lower()}"
    if actual != expected.lower():
        gate.error(
            f"running GitHub repository resolves to {actual!r}, which does not match the "
            f"configured image_repository {image_repository!r}; refusing to publish under "
            "another identity"
        )


def check_public_key(gate: Gate, root: Path, public_key_path: str) -> None:
    source_path = root / (SYSTEM_FILES_PREFIX + public_key_path)
    label = f"fork public key {SYSTEM_FILES_PREFIX}{public_key_path}"
    if not source_path.is_file():
        message = f"{label} does not exist; refusing to publish images no client can verify"
        if gate.allow_missing_key:
            gate.warn(message + " (allowed by --allow-missing-key for local runs)")
            return
        gate.error(message)
        return

    try:
        content = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        gate.error(f"{label} is not readable UTF-8: {exc}")
        return
    stripped = content.strip()
    if not stripped.startswith(PEM_PUBLIC_KEY_START) or not stripped.endswith(
        PEM_PUBLIC_KEY_END
    ):
        gate.error(f"{label} must be a PEM PUBLIC KEY block")
    for marker in FORBIDDEN_KEY_MARKERS:
        if marker in stripped:
            gate.error(
                f"{label} contains {marker!r}; commit the public key only, never a private key"
            )

    openssl = shutil.which("openssl")
    if openssl is None:
        message = (
            "openssl is not available; the fork public key cannot be proven to "
            "parse as a real key — refusing to pass on a PEM appearance check alone"
        )
        if gate.allow_missing_key:
            gate.warn(message + " (allowed by --allow-missing-key for local runs)")
            return
        gate.error(message)
        return
    try:
        result = subprocess.run(
            [openssl, "pkey", "-pubin", "-noout", "-in", str(source_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.SubprocessError as exc:
        gate.error(f"{label} could not be parsed by openssl: {exc}")
        return
    if result.returncode != 0:
        gate.error(
            f"{label} is not a valid public key: {result.stderr.strip() or 'openssl failed'}"
        )


def check_policy(gate: Gate, root: Path, image_repository: str, public_key_path: str) -> None:
    policy = load_json(gate, root, POLICY_JSON, "container trust policy")
    if policy is None:
        return
    transports = policy.get("transports")
    if not isinstance(transports, dict) or not isinstance(transports.get("docker"), dict):
        gate.error(f"{POLICY_JSON}: missing transports.docker scope map")
        return
    docker = transports["docker"]

    if policy.get("default") != [{"type": "reject"}]:
        gate.error(f"{POLICY_JSON}: top-level default must stay [{{\"type\": \"reject\"}}]")

    fork_rules = docker.get(image_repository)
    if not isinstance(fork_rules, list) or not fork_rules:
        gate.error(
            f"{POLICY_JSON}: docker transport has no scope for {image_repository}; without it "
            "fork images fall through to the catch-all scope and are not verified"
        )
    else:
        first = fork_rules[0]
        if first.get("type") != "sigstoreSigned":
            gate.error(
                f"{POLICY_JSON}: fork scope {image_repository} must start with a "
                f"sigstoreSigned rule, got {first.get('type')!r}"
            )
        else:
            if list(first.get("keyPaths") or []) != [public_key_path]:
                gate.error(
                    f"{POLICY_JSON}: fork scope keyPaths must be exactly [{public_key_path}] "
                    "(the release.json public_key_path; upstream keys verify upstream only), "
                    f"got {first.get('keyPaths')!r}"
                )
            identity = first.get("signedIdentity")
            expected_identity = {
                "type": "exactRepository",
                "dockerRepository": image_repository,
            }
            if identity != expected_identity:
                gate.error(
                    f"{POLICY_JSON}: fork scope signedIdentity must be {expected_identity}, "
                    f"got {identity!r}"
                )
        for rule in fork_rules:
            if rule.get("type") in ("insecureAcceptAnything", "accept"):
                gate.error(
                    f"{POLICY_JSON}: fork scope {image_repository} must never accept "
                    "unverified images"
                )

    for scope, expected in EXPECTED_UPSTREAM_RULES.items():
        rules = docker.get(scope)
        if not isinstance(rules, list) or not rules:
            gate.error(f"{POLICY_JSON}: upstream scope {scope} was dropped")
            continue
        first = rules[0]
        if (
            first.get("type") != "sigstoreSigned"
            or list(first.get("keyPaths") or []) != expected["keyPaths"]
            or first.get("signedIdentity") != expected["signedIdentity"]
        ):
            gate.error(
                f"{POLICY_JSON}: upstream scope {scope} changed; expected sigstoreSigned with "
                f"keyPaths {expected['keyPaths']} and signedIdentity "
                f"{expected['signedIdentity']}"
            )


def check_registries_d(gate: Gate, root: Path, image_repository: str) -> None:
    path = root / REGISTRIES_D
    if not path.is_file():
        gate.error(f"sigstore attachment config is missing: {REGISTRIES_D}")
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        gate.error(f"{REGISTRIES_D} is not readable: {exc}")
        return

    # The file only ever holds docker: -> <registry>: -> use-sigstore-attachments:,
    # so a two-level indent scan keeps this dependency-free.
    current_registry = None
    found = False
    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        text = line.strip()
        if indent == 2 and text.endswith(":"):
            current_registry = text[:-1]
        elif (
            indent >= 4
            and current_registry == image_repository
            and text == "use-sigstore-attachments: true"
        ):
            found = True
    if not found:
        gate.error(
            f"{REGISTRIES_D}: {image_repository} must set use-sigstore-attachments: true so "
            "cosign signatures are fetched alongside the image"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="repository tree to check (default: the checkout this script lives in)",
    )
    parser.add_argument(
        "--allow-missing-key",
        action="store_true",
        help="local runs only: warn instead of failing when the fork public key is absent "
        "or cannot be cryptographically validated (no key file, no openssl); "
        "release workflows must not pass this",
    )
    args = parser.parse_args()

    gate = Gate(allow_missing_key=args.allow_missing_key)
    root = args.root.resolve()

    release = check_release_json(gate, root)
    if release is not None and release["image_repository"] and release["public_key_path"]:
        check_running_repository(gate, release["image_repository"])
        check_public_key(gate, root, release["public_key_path"])
        check_policy(gate, root, release["image_repository"], release["public_key_path"])
        check_registries_d(gate, root, release["image_repository"])
    else:
        gate.error("cannot check trust config: release metadata is incomplete")

    return gate.finish()


if __name__ == "__main__":
    sys.exit(main())
