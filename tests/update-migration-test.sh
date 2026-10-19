#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/system_files/usr/lib/armada/update-lib"

FORK_REPO="ghcr.io/heis1696/armadaos-freedom"
TEST_TMP="$(mktemp -d)"
trap 'rm -rf "$TEST_TMP"' EXIT
ARMADA_RELEASE_CONFIG="$TEST_TMP/release.json"
ARMADA_CHANNEL_STATE="$TEST_TMP/channel"

write_config() {
    cat >"$ARMADA_RELEASE_CONFIG" <<EOF
{
  "schema_version": 1,
  "image_repository": "$1",
  "channels": [$2],
  "public_key_path": "${3:-/etc/pki/containers/freedom.pub}"
}
EOF
}

write_config "$FORK_REPO" '"stable", "beta", "testing"'

# Loading the release metadata must produce the fork identity, never an
# implicit upstream identity.
armada_load_release_config
[[ "$ARMADA_FORK_REPOSITORY" == "$FORK_REPO" ]]
[[ "$ARMADA_FORK_CHANNELS" == "stable beta testing" ]]
[[ "$(armada_repository_channels "$FORK_REPO")" == "stable beta testing" ]]
[[ "$(armada_repository_channels "$ARMADA_CANONICAL_REGISTRY")" == "stable beta testing" ]]

# The historical helper signature [booted-tag] remains supported.
(
    armada_booted_registry() { echo "$ARMADA_CANONICAL_REGISTRY"; }
    printf 'beta\n' >"$ARMADA_CHANNEL_STATE"
    [[ "$(armada_desired_channel stable)" == beta ]]
    [[ "$(armada_desired_channel feature-a)" == feature-a ]]
)

assert_registry() {
    local expected="$1" ref="$2" actual
    actual="$(armada_registry_from_ref "$ref")"
    if [[ "$actual" != "$expected" ]]; then
        printf 'registry parse failed: expected %q, got %q for %q\n' \
            "$expected" "$actual" "$ref" >&2
        exit 1
    fi
}

assert_registry "$ARMADA_LEGACY_REGISTRY" \
    "ostree-image-signed:docker://${ARMADA_LEGACY_REGISTRY}:stable"
assert_registry "$ARMADA_CANONICAL_REGISTRY" \
    "ostree-image-signed:docker://${ARMADA_CANONICAL_REGISTRY}@sha256:deadbeef"
assert_registry "$ARMADA_CANONICAL_REGISTRY" \
    "docker://${ARMADA_CANONICAL_REGISTRY}:testing"
assert_registry "$ARMADA_CANONICAL_REGISTRY" \
    "ostree-unverified-registry:${ARMADA_CANONICAL_REGISTRY}:testing"
assert_registry "$FORK_REPO" \
    "ostree-image-signed:docker://${FORK_REPO}:stable"
assert_registry "$FORK_REPO" \
    "ostree-unverified-registry:${FORK_REPO}@sha256:deadbeef"
assert_registry "" \
    "ostree-image-signed:docker://example.invalid/${ARMADA_LEGACY_REGISTRY}:stable"
assert_registry "" \
    "containers-storage:localhost/armada:latest"

assert_repository() {
    local expected="$1" ref="$2" actual
    actual="$(armada_repository_from_ref "$ref" || true)"
    if [[ "$actual" != "$expected" ]]; then
        printf 'repository parse failed: expected %q, got %q for %q\n' \
            "$expected" "$actual" "$ref" >&2
        exit 1
    fi
}

assert_repository "local.armadaos.dev/armada" \
    "ostree-unverified-registry:docker://local.armadaos.dev/armada:feature-a"
assert_repository "$ARMADA_CANONICAL_REGISTRY" \
    "ostree-unverified-registry:${ARMADA_CANONICAL_REGISTRY}:testing"
assert_repository "$FORK_REPO" \
    "ostree-image-signed:docker://${FORK_REPO}:testing"
assert_repository "example.invalid/${ARMADA_LEGACY_REGISTRY}" \
    "ostree-image-signed:docker://example.invalid/${ARMADA_LEGACY_REGISTRY}:stable"
assert_repository "" "containers-storage:localhost/armada:latest"
assert_repository "" "ostree-unverified-registry:docker://containers-storage:localhost/armada:latest"
assert_repository "" "ostree-unverified-registry:containers-storage:localhost/armada:latest"
assert_repository "" "ostree-unverified-registry:docker://invalid"

# Remote inspection must not guess the canonical repository when the booted
# source cannot be resolved.
(
    armada_booted_registry() { :; }
    if armada_remote_info stable >/dev/null 2>&1; then
        echo "remote inspection fell back to an upstream repository" >&2
        exit 1
    fi
)

armada_steam_channels_apply "$ARMADA_CANONICAL_REGISTRY" stable
armada_steam_channels_apply "$ARMADA_LEGACY_REGISTRY" beta
armada_steam_channels_apply "$FORK_REPO" stable
armada_steam_channels_apply "$FORK_REPO" beta
armada_steam_channels_apply "$FORK_REPO" testing
if armada_steam_channels_apply "$FORK_REPO" feature-a; then
    echo "non-channel fork tag unexpectedly uses Steam channels" >&2
    exit 1
fi
if armada_steam_channels_apply "$ARMADA_CANONICAL_REGISTRY" feature-a; then
    echo "non-channel tag unexpectedly uses Steam channels" >&2
    exit 1
fi
if armada_steam_channels_apply "local.armadaos.dev/armada" stable; then
    echo "external registry unexpectedly uses Steam channels" >&2
    exit 1
fi

# Fork channels are exactly the validated JSON list, not the global list.
write_config "$FORK_REPO" '"stable", "beta"'
if armada_steam_channels_apply "$FORK_REPO" testing; then
    echo "fork channel absent from release.json was accepted" >&2
    exit 1
fi
if [[ "$(armada_repository_channels "$FORK_REPO")" != "stable beta" ]]; then
    echo "fork channel list did not come from release.json" >&2
    exit 1
fi
write_config "$FORK_REPO" '"stable", "beta", "testing"'

assert_target() {
    local expected_repository="$1" expected_tag="$2" state="$3" ref="$4" actual
    if [[ "$state" == - ]]; then
        rm -f "$ARMADA_CHANNEL_STATE"
    else
        printf '%s\n' "$state" > "$ARMADA_CHANNEL_STATE"
    fi
    actual="$(armada_update_target "$ref" || true)"
    if [[ "$actual" != "$expected_repository $expected_tag" ]]; then
        printf 'target selection failed: expected %q, got %q for %q\n' \
            "$expected_repository $expected_tag" "$actual" "$ref" >&2
        exit 1
    fi
}

# Fork channel selection and exact fork identity.
assert_target "$FORK_REPO" beta beta \
    "ostree-image-signed:docker://${FORK_REPO}:stable"
assert_target "$FORK_REPO" testing testing \
    "ostree-image-signed:docker://${FORK_REPO}:beta"
assert_target "$FORK_REPO" testing - \
    "ostree-image-signed:docker://${FORK_REPO}:testing"
assert_target "$FORK_REPO" stable invalid \
    "ostree-image-signed:docker://${FORK_REPO}:stable"
assert_target "$FORK_REPO" feature-a beta \
    "ostree-image-signed:docker://${FORK_REPO}:feature-a"
assert_target "$FORK_REPO" beta beta \
    "ostree-image-signed:docker://${FORK_REPO}@sha256:deadbeef"

# Upstream and legacy upstream keep their existing repositories and channels.
assert_target "$ARMADA_CANONICAL_REGISTRY" beta beta \
    "ostree-image-signed:docker://${ARMADA_CANONICAL_REGISTRY}:stable"
assert_target "$ARMADA_LEGACY_REGISTRY" stable stable \
    "ostree-image-signed:docker://${ARMADA_LEGACY_REGISTRY}:testing"
assert_target "$ARMADA_CANONICAL_REGISTRY" stable invalid \
    "ostree-image-signed:docker://${ARMADA_CANONICAL_REGISTRY}:stable"
assert_target "$ARMADA_CANONICAL_REGISTRY" testing - \
    "ostree-image-signed:docker://${ARMADA_CANONICAL_REGISTRY}:testing"
assert_target "$ARMADA_CANONICAL_REGISTRY" feature-a beta \
    "ostree-image-signed:docker://${ARMADA_CANONICAL_REGISTRY}:feature-a"
assert_target "$ARMADA_CANONICAL_REGISTRY" beta beta \
    "ostree-image-signed:docker://${ARMADA_CANONICAL_REGISTRY}@sha256:deadbeef"

# External images keep their original repository and explicit tag.
assert_target "local.armadaos.dev/armada" feature-a beta \
    "ostree-unverified-registry:docker://local.armadaos.dev/armada:feature-a"
assert_target "example.invalid/${ARMADA_LEGACY_REGISTRY}" stable beta \
    "ostree-image-signed:docker://example.invalid/${ARMADA_LEGACY_REGISTRY}:stable"

# A fork channel outside release.json is ignored in favour of the booted tag.
write_config "$FORK_REPO" '"stable", "beta"'
assert_target "$FORK_REPO" stable testing \
    "ostree-image-signed:docker://${FORK_REPO}:stable"
write_config "$FORK_REPO" '"stable", "beta", "testing"'

assert_no_target() {
    local state="$1" ref="$2" actual
    if [[ "$state" == - ]]; then
        rm -f "$ARMADA_CHANNEL_STATE"
    else
        printf '%s\n' "$state" > "$ARMADA_CHANNEL_STATE"
    fi
    if actual=$(armada_update_target "$ref" 2>/dev/null); then
        printf 'target unexpectedly accepted: %q for %q\n' "$actual" "$ref" >&2
        exit 1
    fi
}

# Digest-only refs are allowed only for a trusted repository with a channel
# that can be determined from state.
assert_no_target - \
    "ostree-image-signed:docker://${FORK_REPO}@sha256:deadbeef"
assert_no_target invalid \
    "ostree-image-signed:docker://${FORK_REPO}@sha256:deadbeef"
assert_no_target beta \
    "ostree-unverified-registry:docker://local.armadaos.dev/armada@sha256:deadbeef"
assert_no_target beta \
    "ostree-image-signed:docker://example.invalid/${ARMADA_LEGACY_REGISTRY}@sha256:deadbeef"
(
    armada_booted_channel() { :; }
    assert_no_target - \
        "ostree-image-signed:docker://${ARMADA_CANONICAL_REGISTRY}@sha256:deadbeef"
)

# Local storage and unparseable sources never fall back to upstream.
assert_no_target beta "containers-storage:localhost/armada:latest"
assert_no_target beta \
    "ostree-unverified-registry:docker://containers-storage:localhost/armada:latest"
assert_no_target beta "ostree-unverified-registry:docker://invalid"
assert_no_target beta "ostree-unverified-registry:"
assert_no_target beta ""

# Missing, corrupt or schema-invalid release metadata fails closed for every
# source instead of silently using the canonical upstream repository.
mv "$ARMADA_RELEASE_CONFIG" "$TEST_TMP/release.json.saved"
assert_no_target beta \
    "ostree-image-signed:docker://${FORK_REPO}:stable"
assert_no_target beta \
    "ostree-image-signed:docker://${ARMADA_CANONICAL_REGISTRY}:stable"
printf '{' >"$ARMADA_RELEASE_CONFIG"
assert_no_target beta \
    "ostree-image-signed:docker://${FORK_REPO}:stable"
write_config "$FORK_REPO" '"stable", "canary"'
assert_no_target beta \
    "ostree-image-signed:docker://${FORK_REPO}:stable"
write_config "ghcr.io/heis1696/armadaos-freedom:stable" '"stable"'
assert_no_target beta \
    "ostree-image-signed:docker://${FORK_REPO}:stable"
mv "$TEST_TMP/release.json.saved" "$ARMADA_RELEASE_CONFIG"

UPDATE="$ROOT/system_files/usr/libexec/armada/armada-update"
grep -Fq 'if armada_steam_channels_apply "$repository" "$desired"; then' "$UPDATE"

python3 - "$ROOT" <<'PY'
import json
from pathlib import Path
import sys
import tomllib

root = Path(sys.argv[1])
canonical = "ghcr.io/armada-os/armada"
legacy = "ghcr.io/virtudude/armada"
mirror_path = (
    root / "system_files/etc/containers/registries.conf.d/50-armada-migration.conf"
)

policy = json.loads(
    (root / "system_files/etc/containers/policy.json").read_text()
)
docker = policy["transports"]["docker"]
assert docker[legacy][0]["signedIdentity"] == {
    "type": "exactRepository",
    "dockerRepository": canonical,
}
assert docker[canonical][0]["signedIdentity"] == {"type": "matchRepository"}

assert mirror_path.is_file()
assert not (
    root
    / "system_files/usr/share/containers/registries.conf.d/50-armada-migration.conf"
).exists()
mirror = tomllib.loads(mirror_path.read_text())
registry = mirror["registry"][0]
assert registry["prefix"] == legacy
assert registry["location"] == legacy
assert registry["mirror"] == [{"location": canonical}]

sigstore = (
    root / "system_files/etc/containers/registries.d/ghcr-armada.yaml"
).read_text()
for repository in (legacy, canonical):
    assert f"  {repository}:\n    use-sigstore-attachments: true" in sigstore
PY

printf 'update repository migration test passed\n'
