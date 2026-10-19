#!/usr/bin/env bash
# Fork signing closed loop: release gate, client trust policy, signature-result
# checking, and — when cosign is available — a real offline signature roundtrip
# with a temporary key. Keys are generated under a mktemp directory and never
# committed.
#
# What each layer proves:
#   [config] release.json / policy.json / registries.d / workflow wiring
#   [script] verify-release-config.py accept/reject behavior in sandbox trees
#   [helper] verify-signature-result.py accept/reject behavior (identity+digest)
#   [crypto] cosign sign+verify with a temporary key (offline payload mode),
#            including correct vs wrong signed repository identity
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
HELPER = ROOT / ".github/scripts/verify-signature-result.py"
BUILD_YML = ROOT / ".github/workflows/build.yml"
PROMOTE_YML = ROOT / ".github/workflows/promote.yml"
RELEASE_REL = "system_files/usr/share/armada/release.json"
POLICY_REL = "system_files/etc/containers/policy.json"
REGISTRIES_REL = "system_files/etc/containers/registries.d/ghcr-armada.yaml"
SCHEMA_HELPER_REL = "system_files/usr/lib/armada/release_config.py"
REPO = "ghcr.io/heis1696/armadaos-freedom"
GITHUB_REPOSITORY_IDENTITY = "heis1696/armadaos-freedom"
KEY_IN_IMAGE = "/etc/pki/containers/freedom.pub"
KEY_SOURCE_REL = "system_files" + KEY_IN_IMAGE
# "hello" — an arbitrary fixture digest for offline payloads.
FIXTURE_DIGEST = "sha256:" + "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
UPSTREAM_REPO = "ghcr.io/armada-os/armada"

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


def run_gate(root, *args, github_repository=GITHUB_REPOSITORY_IDENTITY, path=None):
    env = dict(os.environ)
    if github_repository is None:
        env.pop("GITHUB_REPOSITORY", None)
    else:
        env["GITHUB_REPOSITORY"] = github_repository
    if path is not None:
        # sys.executable is absolute, so only shutil.which("openssl") inside
        # the gate sees this stripped PATH.
        env["PATH"] = path
    return subprocess.run(
        [sys.executable, str(GATE), "--root", str(root), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


def run_helper(text, identity=REPO, digest=FIXTURE_DIGEST):
    return subprocess.run(
        [sys.executable, str(HELPER), "--identity", identity, "--digest", digest],
        input=text,
        capture_output=True,
        text=True,
        timeout=120,
    )


def make_sandbox(key_bytes=None):
    """Isolated copy of the release-config files; tests never touch the tree."""
    root = Path(tempfile.mkdtemp(prefix="fork-signing-"))
    for rel in (RELEASE_REL, POLICY_REL, REGISTRIES_REL, SCHEMA_HELPER_REL):
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


def signature_entry(identity, digest):
    return {
        "critical": {
            "identity": {"docker-reference": identity},
            "image": {"docker-manifest-digest": digest},
            "type": "cosign container image signature",
        },
        "optional": None,
    }


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
    docker_scopes.get(UPSTREAM_REPO, [{}])[0].get("keyPaths")
    == [UPSTREAM_ARMADA_KEY, "/etc/pki/containers/armada-backup.pub"],
)
check(
    "legacy scope kept with canonical signedIdentity",
    docker_scopes.get("ghcr.io/virtudude/armada", [{}])[0].get("signedIdentity")
    == {"type": "exactRepository", "dockerRepository": UPSTREAM_REPO},
)
check("top-level default stays reject", policy.get("default") == [{"type": "reject"}])

registries = (ROOT / REGISTRIES_REL).read_text()
check(
    "sigstore attachments enabled for the fork repository",
    f"  {REPO}:" in registries and "use-sigstore-attachments: true" in registries,
)

build = BUILD_YML.read_text()
promote = PROMOTE_YML.read_text()
gate_step = build.find("Verify release signing config")
packages_job = build.find("\n  packages:\n")
push_job = build.find("\n  build_push:\n")
check(
    "build.yml has a preflight release-gate job before the packages job",
    0 <= gate_step < packages_job < push_job,
)
check(
    "build.yml gates the packages job on the preflight gate",
    "\n  packages:\n    name: Packages\n    needs: verify_release_config\n" in build,
)
check(
    "build.yml gates build_push on the preflight gate",
    "needs: [verify_release_config, packages]" in build,
)
check(
    "build.yml runs the release gate before push/sign",
    0
    <= gate_step
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
    "build.yml self-verify checks signed identity and digest via the helper",
    "verify-signature-result.py" in build
    and '--identity "${EXPECTED_IDENTITY}" --digest "${EXPECTED_DIGEST}"' in build,
)
check(
    "promote.yml runs the release gate before any registry action",
    0 <= promote.find("Verify release signing config") < promote.find("Log in to GHCR"),
)
check(
    "promote.yml promotes under the same release.json identity and key",
    'cosign verify --key "${RELEASE_PUBKEY}"' in promote and "armada.pub" not in promote,
)
check(
    "promote.yml checks signed identity and digest via the helper",
    "verify-signature-result.py" in promote
    and '--identity "${REPO}" --digest "${DIGEST}"' in promote,
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
            data["transports"]["docker"].pop(UPSTREAM_REPO, None)

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

        def boolean_schema_version(data):
            data["schema_version"] = True

        inconsistent = make_sandbox(key_bytes=valid_key)
        edit_json(inconsistent, RELEASE_REL, boolean_schema_version)
        proc = run_gate(inconsistent)
        check(
            "schema_version=true is rejected by the runtime schema (not coerced)",
            proc.returncode != 0 and "schema_version" in proc.stderr,
            proc.stderr.strip(),
        )

        duplicate = make_sandbox(key_bytes=valid_key)
        (duplicate / RELEASE_REL).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "image_repository": REPO,
                    "channels": ["stable", "beta", "testing"],
                    "public_key_path": KEY_IN_IMAGE,
                }
            ).replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1', 1)
        )
        proc = run_gate(duplicate)
        check(
            "duplicate JSON fields are rejected by the runtime schema",
            proc.returncode != 0 and "duplicate field" in proc.stderr,
            proc.stderr.strip(),
        )

        missing_helper = make_sandbox(key_bytes=valid_key)
        (missing_helper / SCHEMA_HELPER_REL).unlink()
        proc = run_gate(missing_helper)
        check(
            "missing runtime schema helper fails the gate closed",
            proc.returncode != 0 and "schema helper" in proc.stderr,
            proc.stderr.strip(),
        )

        no_attachments = make_sandbox(key_bytes=valid_key)
        text = (no_attachments / REGISTRIES_REL).read_text().replace(f"  {REPO}:\n    use-sigstore-attachments: true\n", "")
        (no_attachments / REGISTRIES_REL).write_text(text)
        proc = run_gate(no_attachments)
        check(
            "registry without fork sigstore attachments is rejected",
            proc.returncode != 0 and "use-sigstore-attachments" in proc.stderr,
        )

        if openssl:
            stripped = make_sandbox(key_bytes=valid_key)
            proc = run_gate(stripped, path="/nonexistent")
            check(
                "missing openssl fails release mode (no PEM-appearance fallback)",
                proc.returncode != 0 and "openssl" in proc.stderr,
                proc.stderr.strip(),
            )
            proc = run_gate(stripped, "--allow-missing-key", path="/nonexistent")
            check(
                "missing openssl only warns with --allow-missing-key",
                proc.returncode == 0,
                proc.stderr.strip(),
            )
        else:
            skip("missing-openssl gate cases", "openssl not on PATH to strip")

    print("[helper] verify-signature-result.py accept/reject behavior")
    good = json.dumps([signature_entry(REPO, FIXTURE_DIGEST)])
    proc = run_helper(good)
    check(
        "helper accepts a verified signature with the exact identity and digest",
        proc.returncode == 0,
        proc.stderr.strip(),
    )
    proc = run_helper(json.dumps([]))
    check(
        "helper rejects an empty verified-signature list",
        proc.returncode != 0 and "no signatures" in proc.stderr,
        proc.stderr.strip(),
    )
    proc = run_helper("")
    check("helper rejects empty cosign output", proc.returncode != 0, proc.stderr.strip())
    proc = run_helper(json.dumps([signature_entry(UPSTREAM_REPO, FIXTURE_DIGEST)]))
    check(
        "helper rejects a signature whose identity is another repository",
        proc.returncode != 0 and "no verified signature matches" in proc.stderr,
        proc.stderr.strip(),
    )
    proc = run_helper(json.dumps([signature_entry(REPO, "sha256:" + "1" * 64)]))
    check(
        "helper rejects a signature claimed for a different digest",
        proc.returncode != 0 and "no verified signature matches" in proc.stderr,
        proc.stderr.strip(),
    )
    proc = run_helper(json.dumps(signature_entry(REPO, FIXTURE_DIGEST)))
    check(
        "helper rejects a non-array cosign output",
        proc.returncode != 0 and "not a JSON array" in proc.stderr,
        proc.stderr.strip(),
    )

    if cosign:
        print("[crypto] cosign roundtrip with a temporary key (offline payload mode)")
        env = dict(os.environ, COSIGN_PASSWORD="")
        digest = FIXTURE_DIGEST
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

        def verify_and_check(payload_obj, identity, digest_value):
            """Full CI pipeline: real cosign verify output through the helper."""
            payload_path = keydir / "case-payload.json"
            payload_path.write_text(json.dumps(payload_obj))
            sig_path = keydir / "case-sig.b64"
            with open(sig_path, "wb") as sink:
                subprocess.run(
                    [cosign, "sign-blob", "--key", str(keydir / "cosign.key"), "--tlog-upload=false", str(payload_path)],
                    check=True,
                    stdout=sink,
                    env=env,
                    timeout=120,
                )
            verified = subprocess.run(
                [
                    cosign, "verify", "--insecure-ignore-tlog",
                    "--key", str(keydir / "cosign.pub"),
                    "--payload", str(payload_path),
                    "--signature", str(sig_path),
                    f"{REPO}@{digest_value}",
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=120,
            )
            helper = subprocess.run(
                [sys.executable, str(HELPER), "--identity", identity, "--digest", digest_value],
                input=verified.stdout,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return verified.returncode, helper.returncode, helper.stderr

        bare = {
            "critical": {
                "identity": {"docker-reference": REPO},
                "image": {"docker-manifest-digest": digest},
                "type": "cosign container image signature",
            },
            "optional": None,
        }
        verified_rc, helper_rc, helper_err = verify_and_check(bare, REPO, digest)
        check(
            "bare-repository identity: cosign verifies and the helper accepts",
            verified_rc == 0 and helper_rc == 0,
            f"cosign={verified_rc} helper={helper_rc} {helper_err.strip()}",
        )

        foreign = {
            "critical": {
                "identity": {"docker-reference": UPSTREAM_REPO},
                "image": {"docker-manifest-digest": digest},
                "type": "cosign container image signature",
            },
            "optional": None,
        }
        verified_rc, helper_rc, helper_err = verify_and_check(foreign, REPO, digest)
        check(
            "wrong-repository identity: cosign key+digest verification still passes (known gap)",
            verified_rc == 0,
            f"cosign unexpectedly failed: rc={verified_rc}",
        )
        check(
            "wrong-repository identity: the helper rejects the same signature",
            helper_rc != 0 and "no verified signature matches" in helper_err,
            helper_err.strip(),
        )
        print(
            "    note: cosign key verification binds key+digest only; the repository"
            " identity in the ref is NOT checked by cosign — CI closes this with"
            " verify-signature-result.py (exercised above), and pull-time"
            " enforcement stays policy.json signedIdentity exactRepository"
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
