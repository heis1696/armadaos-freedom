#!/usr/bin/env bash
# Fork signing closed loop: release gate, client trust policy, and — when
# cosign is available — a real offline signature roundtrip with a temporary
# key. Keys are generated under a mktemp directory and never committed.
#
# What each layer proves:
#   [config] release.json / policy.json / registries.d / workflow wiring
#   [script] verify-release-config.py accept/reject behavior in sandbox trees
#   [crypto] cosign sign+verify with a temporary key (offline payload mode)
#
# Not covered anywhere: a real GHCR push + on-device containers/image pull.
# The crypto layer proves the key/signature mechanics only; policy.json
# enforcement at pull time is asserted as configuration, not executed.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export ARMADA_TEST_ROOT="$ROOT"

python3 - "$ROOT" <<'PY'
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(sys.argv[1])
GATE = ROOT / ".github/scripts/verify-release-config.py"
BUILD_YML = ROOT / ".github/workflows/build.yml"
PROMOTE_YML = ROOT / ".github/workflows/promote.yml"
RELEASE_REL = "system_files/usr/share/armada/release.json"
POLICY_REL = "system_files/etc/containers/policy.json"
REGISTRIES_REL = "system_files/etc/containers/registries.d/ghcr-armada.yaml"
REPO = "ghcr.io/heis1696/armadaos-freedom"
GITHUB_REPOSITORY_IDENTITY = "heis1696/armadaos-freedom"
KEY_IN_IMAGE = "/etc/pki/containers/freedom.pub"
KEY_SOURCE_REL = "system_files" + KEY_IN_IMAGE

results = {"pass": 0, "fail": 0, "skip": 0}


def check(name, ok, detail=""):
    results["pass" if ok else "fail"] += 1
    status = "ok" if ok else "FAIL"
    suffix = f": {detail}" if detail and not ok else ""
    print(f"    [{status}] {name}{suffix}")
    return ok


def skip(name, reason):
    results["skip"] += 1
    print(f"    [SKIP] {name}: {reason}")


def section(title):
    print(f"  == {title}")


def run_gate(root, *args, github_repository=GITHUB_REPOSITORY_IDENTITY):
    env = dict(os.environ)
    if github_repository is None:
        env.pop("GITHUB_REPOSITORY", None)
    else:
        env["GITHUB_REPOSITORY"] = github_repository
    return subprocess.run(
        [sys.executable, str(GATE), "--root", str(root), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


def make_sandbox(key_bytes=None):
    """Isolated copy of the release-config files; tests never touch the tree."""
    root = Path(tempfile.mkdtemp(prefix="fork-signing-"))
    for rel in (RELEASE_REL, POLICY_REL, REGISTRIES_REL):
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, target)
    if key_bytes is not None:
        key_path = root / KEY_SOURCE_REL
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(key_bytes)
    return root


def edit_json(root, rel, mutate):
    path = root / rel
    data = json.loads(path.read_text())
    mutate(data)
    path.write_text(json.dumps(data, indent=4))


FORK_SCOPE_RULE = {
    "type": "sigstoreSigned",
    "keyPaths": [KEY_IN_IMAGE],
    "signedIdentity": {
        "type": "exactRepository",
        "dockerRepository": REPO,
    },
}
UPSTREAM_ARMADA_KEY = "/etc/pki/containers/armada.pub"

print("[config] release identity and client trust data on the real tree")
release = json.loads((ROOT / RELEASE_REL).read_text())
check("image_repository is the fork repository", release.get("image_repository") == REPO)
check("public_key_path matches the policy key path", release.get("public_key_path") == KEY_IN_IMAGE)
check("channels are stable/beta/testing", release.get("channels") == ["stable", "beta", "testing"])

policy = json.loads((ROOT / POLICY_REL).read_text())
docker_scopes = policy["transports"]["docker"]
check(
    "policy has an exact fork scope (never the catch-all)",
    docker_scopes.get(REPO, [{}])[0].get("type") == "sigstoreSigned"
    and docker_scopes.get(REPO, [{}])[0].get("keyPaths") == [KEY_IN_IMAGE]
    and docker_scopes.get(REPO, [{}])[0].get("signedIdentity")
    == {"type": "exactRepository", "dockerRepository": REPO},
)
check(
    "upstream canonical scope kept on its own keys",
    docker_scopes.get("ghcr.io/armada-os/armada", [{}])[0].get("keyPaths")
    == [UPSTREAM_ARMADA_KEY, "/etc/pki/containers/armada-backup.pub"],
)
check(
    "legacy scope kept with canonical signedIdentity",
    docker_scopes.get("ghcr.io/virtudude/armada", [{}])[0].get("signedIdentity")
    == {"type": "exactRepository", "dockerRepository": "ghcr.io/armada-os/armada"},
)
check("top-level default stays reject", policy.get("default") == [{"type": "reject"}])

registries = (ROOT / REGISTRIES_REL).read_text()
check(
    "sigstore attachments enabled for the fork repository",
    f"  {REPO}:" in registries and "use-sigstore-attachments: true" in registries,
)

build = BUILD_YML.read_text()
promote = PROMOTE_YML.read_text()
check(
    "build.yml runs the release gate before push/sign",
    0
    <= build.find("Verify release signing config")
    < min(x for x in (build.find("Push container to GHCR"), build.find("Sign container image")) if x >= 0),
)
check(
    "build.yml has no fork skip around verification",
    'github.event.repository.fork }}" != "true"' not in build,
)
check(
    "build.yml self-verifies with the release.json key",
    "RELEASE_PUBKEY=" in build and 'cosign verify --key "${RELEASE_PUBKEY}"' in build,
)
check(
    "promote.yml runs the release gate before any registry action",
    0 <= promote.find("Verify release signing config") < promote.find("Log in to GHCR"),
)
check(
    "promote.yml promotes under the same release.json identity and key",
    'cosign verify --key "${RELEASE_PUBKEY}"' in promote and "armada.pub" not in promote,
)

print("[script] verify-release-config.py behavior (sandboxed trees)")
if not (ROOT / KEY_SOURCE_REL).exists():
    proc = run_gate(ROOT)
    check(
        "real tree without the public key fails release mode explicitly",
        proc.returncode != 0 and "fork public key" in proc.stderr,
        proc.stderr.strip().splitlines()[-1] if proc.stderr else "no output",
    )
    proc = run_gate(ROOT, "--allow-missing-key")
    check(
        "real tree static checks pass keyless for local runs",
        proc.returncode == 0,
        proc.stderr.strip(),
    )
else:
    skip("missing-key release failure", f"{KEY_SOURCE_REL} exists in this checkout")

with tempfile.TemporaryDirectory(prefix="fork-signing-keys-") as keydir:
    keydir = Path(keydir)
    key_pub = keydir / "freedom.pub"
    key_priv = keydir / "freedom-private.enc"
    cosign = shutil.which("cosign")
    openssl = shutil.which("openssl")
    if cosign:
        env = dict(os.environ, COSIGN_PASSWORD="")
        subprocess.run(
            [cosign, "generate-key-pair", "--output-key-prefix", str(keydir / "cosign")],
            check=True,
            capture_output=True,
            env=env,
            timeout=120,
        )
        shutil.copyfile(keydir / "cosign.pub", key_pub)
        key_priv = keydir / "cosign.key"
    elif openssl:
        subprocess.run(
            [openssl, "genpkey", "-algorithm", "ed25519", "-out", str(key_priv)],
            check=True,
            capture_output=True,
            timeout=120,
        )
        subprocess.run(
            [openssl, "pkey", "-in", str(key_priv), "-pubout", "-out", str(key_pub)],
            check=True,
            capture_output=True,
            timeout=120,
        )
    else:
        skip("key-dependent gate cases", "neither cosign nor openssl is available")

    if key_pub.exists():
        valid_key = key_pub.read_bytes()

        root = make_sandbox(key_bytes=valid_key)
        proc = run_gate(root)
        check("success path: valid key, matching repo", proc.returncode == 0, proc.stderr.strip())

        proc = run_gate(root, github_repository="evil/lookalike")
        check(
            "running repository differing from image_repository is rejected",
            proc.returncode != 0 and "image_repository" in proc.stderr,
        )

        missing = make_sandbox()
        proc = run_gate(missing)
        check("missing public key fails release mode", proc.returncode != 0 and "fork public key" in proc.stderr)
        proc = run_gate(missing, "--allow-missing-key")
        check("missing public key only warns with --allow-missing-key", proc.returncode == 0, proc.stderr.strip())

        private = make_sandbox(key_bytes=key_priv.read_bytes())
        proc = run_gate(private)
        check(
            "a committed private key is rejected",
            proc.returncode != 0 and "never a private key" in proc.stderr,
        )

        def drop_fork_scope(data):
            data["transports"]["docker"].pop(REPO, None)

        inconsistent = make_sandbox(key_bytes=valid_key)
        edit_json(inconsistent, POLICY_REL, drop_fork_scope)
        proc = run_gate(inconsistent)
        check(
            "policy without the fork scope is rejected (no insecure fall-through)",
            proc.returncode != 0 and "no scope for" in proc.stderr,
        )

        def accept_fork(data):
            data["transports"]["docker"][REPO] = [{"type": "insecureAcceptAnything"}]

        inconsistent = make_sandbox(key_bytes=valid_key)
        edit_json(inconsistent, POLICY_REL, accept_fork)
        proc = run_gate(inconsistent)
        check("fork scope accepting anything is rejected", proc.returncode != 0)

        def trust_upstream_key_for_fork(data):
            data["transports"]["docker"][REPO] = [dict(FORK_SCOPE_RULE, keyPaths=[UPSTREAM_ARMADA_KEY])]

        inconsistent = make_sandbox(key_bytes=valid_key)
        edit_json(inconsistent, POLICY_REL, trust_upstream_key_for_fork)
        proc = run_gate(inconsistent)
        check(
            "fork scope pointing at the upstream key is rejected",
            proc.returncode != 0 and "keyPaths" in proc.stderr,
        )

        def drop_upstream(data):
            data["transports"]["docker"].pop("ghcr.io/armada-os/armada", None)

        inconsistent = make_sandbox(key_bytes=valid_key)
        edit_json(inconsistent, POLICY_REL, drop_upstream)
        proc = run_gate(inconsistent)
        check("dropped upstream canonical scope is rejected", proc.returncode != 0)

        def rebrand_repository(data):
            data["image_repository"] = "ghcr.io/someone/else"

        inconsistent = make_sandbox(key_bytes=valid_key)
        edit_json(inconsistent, RELEASE_REL, rebrand_repository)
        proc = run_gate(inconsistent)
        check(
            "image_repository moved away from the running repository is rejected",
            proc.returncode != 0,
        )

        def change_channels(data):
            data["channels"] = ["stable", "beta"]

        inconsistent = make_sandbox(key_bytes=valid_key)
        edit_json(inconsistent, RELEASE_REL, change_channels)
        proc = run_gate(inconsistent)
        check("contract channel set change is rejected", proc.returncode != 0)

        no_attachments = make_sandbox(key_bytes=valid_key)
        text = (no_attachments / REGISTRIES_REL).read_text().replace(f"  {REPO}:\n    use-sigstore-attachments: true\n", "")
        (no_attachments / REGISTRIES_REL).write_text(text)
        proc = run_gate(no_attachments)
        check(
            "registry without fork sigstore attachments is rejected",
            proc.returncode != 0 and "use-sigstore-attachments" in proc.stderr,
        )

    if cosign:
        print("[crypto] cosign roundtrip with a temporary key (offline payload mode)")
        env = dict(os.environ, COSIGN_PASSWORD="")
        digest = "sha256:" + "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        payload = keydir / "payload.json"
        payload.write_text(
            json.dumps(
                {
                    "critical": {
                        "identity": {"docker-reference": f"{REPO}:testing"},
                        "image": {"docker-manifest-digest": digest},
                        "type": "cosign container image signature",
                    },
                    "optional": None,
                }
            )
        )
        signature = keydir / "signature.b64"
        with open(signature, "wb") as sink:
            subprocess.run(
                [cosign, "sign-blob", "--key", str(keydir / "cosign.key"), "--tlog-upload=false", str(payload)],
                check=True,
                stdout=sink,
                env=env,
                timeout=120,
            )

        def cosign_verify(key, ref):
            return subprocess.run(
                [
                    cosign, "verify", "--insecure-ignore-tlog",
                    "--key", str(key),
                    "--payload", str(payload),
                    "--signature", str(signature),
                    ref,
                ],
                capture_output=True,
                env=env,
                timeout=120,
            ).returncode

        check(
            "signature by the release key verifies for the exact digest",
            cosign_verify(keydir / "cosign.pub", f"{REPO}@{digest}") == 0,
        )
        subprocess.run(
            [cosign, "generate-key-pair", "--output-key-prefix", str(keydir / "other")],
            check=True,
            capture_output=True,
            env=env,
            timeout=120,
        )
        check(
            "signature does not verify under a different key",
            cosign_verify(keydir / "other.pub", f"{REPO}@{digest}") != 0,
        )
        check(
            "signature does not verify for a different digest",
            cosign_verify(keydir / "cosign.pub", f"{REPO}@sha256:{'1' * 64}") != 0,
        )
        print(
            "    note: cosign key verification binds key+digest only; the repository"
            " identity in the ref is NOT checked by cosign — exact identity"
            " enforcement is policy.json signedIdentity exactRepository"
            " (asserted at the config layer above)."
        )
        print(
            "    boundary: registry upload, sigstore attachment fetch, and on-device"
            " containers/image policy enforcement were NOT exercised here."
        )
    else:
        skip(
            "cosign roundtrip",
            "cosign not on PATH — end-to-end signature behavior NOT verified in this run",
        )

print(
    f"[summary] pass={results['pass']} fail={results['fail']} skip={results['skip']}"
)
if results["fail"]:
    sys.exit(1)
PY
