#!/usr/bin/env python3
"""Read and validate the fork release metadata as data.

The only trusted source for the fork image identity is
``/usr/share/armada/release.json`` (``system_files/usr/share/armada/release.json``
in the repository).  The file is never sourced or evaluated by a shell.

``update-lib`` invokes this module with ``python3 release_config.py --config
PATH`` and consumes the single output line ``repository<TAB>channel ...``.
It also invokes ``--reference REF`` to parse a booted container image
reference down to its repository; :func:`parse_image_reference` is the same
parser as a library function.  Tests may import :func:`load_release_config`
directly and point it at a temporary copy of the file.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
import re
import sys


DEFAULT_CONFIG_PATH = "/usr/share/armada/release.json"
MAX_CONFIG_BYTES = 64 * 1024
SCHEMA_VERSION = 1
# These are the branch tokens Steam knows how to select.  A fork may publish a
# subset, but it must not invent a fourth token that the Steam hooks cannot map.
ALLOWED_CHANNELS = frozenset({"stable", "beta", "testing"})
REQUIRED_FIELDS = frozenset(
    {"schema_version", "image_repository", "channels", "public_key_path"}
)

# A full repository name: registry[/namespace...]/name.  Tags, digests and
# transports are not accepted.  Registry and repository components are
# lowercase to match OCI/Docker reference rules.
_HOST_LABEL = r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
_REGISTRY = rf"(?:{_HOST_LABEL}\.)*{_HOST_LABEL}(?::[0-9]{{1,5}})?"
_COMPONENT = r"[a-z0-9]+(?:(?:[._]|__|[-]+)[a-z0-9]+)*"
_REPOSITORY_RE = re.compile(rf"^{_REGISTRY}/{_COMPONENT}(?:/{_COMPONENT})*$")
_TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
# bootc/containers signatures are sha256 based; a digest is never guessed.
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_CHANNEL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_KEY_PATH_RE = re.compile(r"^(?:/[A-Za-z0-9._-]+)+$")

# The complete container-image-reference prefixes written by rpm-ostree/bootc
# (and the plain docker:// transport).  A reference must start with one of
# these exactly; shorter/garbage prefixes hide a nested transport.
SUPPORTED_TRANSPORTS = (
    "ostree-image-signed:docker://",
    "ostree-unverified-image:docker://",
    "ostree-unverified-registry:",
    "docker://",
)
# Local storage/importer transports are never network update sources, even
# when they follow an accepted prefix.
LOCAL_TRANSPORTS = (
    "atomic:",
    "containers-storage:",
    "dir:",
    "docker-archive:",
    "docker-daemon:",
    "docker:",
    "oci:",
    "oci-archive:",
    "ostree:",
    "ostree-remote-registry:",
    "sif:",
    "tarball:",
)


class ReleaseConfigError(ValueError):
    """The release metadata is missing, unreadable or invalid."""


@dataclass(frozen=True)
class ReleaseConfig:
    schema_version: int
    image_repository: str
    channels: tuple[str, ...]
    public_key_path: str


@dataclass(frozen=True)
class ImageReference:
    """A validated ``name[:tag][@sha256:digest]`` image reference."""

    repository: str
    tag: str | None
    digest: str | None


def _object_without_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseConfigError(f"duplicate field: {key}")
        result[key] = value
    return result


def load_release_config(path=None) -> ReleaseConfig:
    """Load and validate a release metadata file.

    Raises :class:`ReleaseConfigError` for a missing file, malformed JSON,
    wrong schema, or any repository/channel/key value that cannot be trusted.
    """

    if path is None:
        path = DEFAULT_CONFIG_PATH
    path = Path(path)

    try:
        size = path.stat().st_size
    except OSError as error:
        raise ReleaseConfigError(
            f"cannot read {path}: {error.strerror or error}"
        ) from error
    if size > MAX_CONFIG_BYTES:
        raise ReleaseConfigError(f"{path} is larger than {MAX_CONFIG_BYTES} bytes")

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ReleaseConfigError(f"cannot read {path}: {error}") from error

    try:
        data = json.loads(text, object_pairs_hook=_object_without_duplicates)
    except json.JSONDecodeError as error:
        raise ReleaseConfigError(f"{path} is not valid JSON: {error.msg}") from error

    if not isinstance(data, dict):
        raise ReleaseConfigError(f"{path} must contain a JSON object")

    missing = REQUIRED_FIELDS - set(data)
    if missing:
        raise ReleaseConfigError(
            f"{path} is missing required fields: {', '.join(sorted(missing))}"
        )
    unknown = set(data) - REQUIRED_FIELDS
    if unknown:
        raise ReleaseConfigError(
            f"{path} has unknown fields: {', '.join(sorted(unknown))}"
        )

    version = data["schema_version"]
    if type(version) is not int or version != SCHEMA_VERSION:
        raise ReleaseConfigError(
            f"{path} schema_version must be the integer {SCHEMA_VERSION}"
        )

    repository = data["image_repository"]
    if not isinstance(repository, str) or not _REPOSITORY_RE.fullmatch(repository):
        raise ReleaseConfigError(
            f"{path} image_repository must be a full lowercase registry/repository"
        )

    channels = data["channels"]
    if not isinstance(channels, list) or not channels:
        raise ReleaseConfigError(f"{path} channels must be a non-empty list")
    for channel in channels:
        if not isinstance(channel, str) or not _CHANNEL_RE.fullmatch(channel):
            raise ReleaseConfigError(f"{path} has an invalid channel name")
        if channel not in ALLOWED_CHANNELS:
            raise ReleaseConfigError(
                f"{path} has an unsupported channel: {channel}"
            )
    if len(set(channels)) != len(channels):
        raise ReleaseConfigError(f"{path} channels must not contain duplicates")

    key_path = data["public_key_path"]
    if not isinstance(key_path, str) or not _KEY_PATH_RE.fullmatch(key_path):
        raise ReleaseConfigError(
            f"{path} public_key_path must be an absolute, simple file path"
        )
    if any(component in (".", "..") for component in key_path.split("/")[1:]):
        raise ReleaseConfigError(
            f"{path} public_key_path must not contain relative components"
        )

    return ReleaseConfig(
        schema_version=version,
        image_repository=repository,
        channels=tuple(channels),
        public_key_path=key_path,
    )


def parse_image_reference(reference) -> ImageReference:
    """Validate one booted container-image-reference.

    The reference must use exactly one supported, complete transport prefix and
    then be a well-formed OCI reference: ``registry/repository[:tag][@digest]``.
    Nested or local transports and malformed names, tags or digests are
    rejected instead of being stripped down to a guessable repository.  This is
    deliberately fail-closed: callers must never fall back to another
    repository.

    Raises :class:`ReleaseConfigError` for any unsupported or malformed value.
    """

    if not isinstance(reference, str) or not reference:
        raise ReleaseConfigError("image reference must be a non-empty string")

    remainder = None
    for transport in SUPPORTED_TRANSPORTS:
        if reference.startswith(transport):
            remainder = reference[len(transport):]
            break
    if remainder is None:
        raise ReleaseConfigError(
            f"image reference has no supported transport: {reference!r}"
        )
    if not remainder:
        raise ReleaseConfigError("image reference is empty after its transport")
    # A second transport layer (docker://, oci://, ...) is never part of an
    # OCI name, and whitespace/control characters cannot appear in one.
    if "://" in remainder:
        raise ReleaseConfigError(f"image reference nests a transport: {reference!r}")
    if any(
        character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F
        for character in remainder
    ):
        raise ReleaseConfigError(
            f"image reference contains whitespace or control characters: {reference!r}"
        )
    for transport in LOCAL_TRANSPORTS:
        if remainder.startswith(transport):
            raise ReleaseConfigError(
                f"local image transport is not an update source: {reference!r}"
            )

    name = remainder
    digest = None
    tag = None
    if "@" in name:
        if name.count("@") != 1:
            raise ReleaseConfigError(f"image reference has an invalid digest: {reference!r}")
        name, _, digest = name.partition("@")
        if not _DIGEST_RE.fullmatch(digest):
            raise ReleaseConfigError(f"image reference has an invalid digest: {reference!r}")
    last = name.rsplit("/", 1)[-1]
    if ":" in last:
        name, _, tag = name.rpartition(":")
        if not _TAG_RE.fullmatch(tag):
            raise ReleaseConfigError(f"image reference has an invalid tag: {reference!r}")
    if not _REPOSITORY_RE.fullmatch(name):
        raise ReleaseConfigError(
            f"image reference has an invalid repository: {reference!r}"
        )

    return ImageReference(repository=name, tag=tag, digest=digest)


def shell_line(config: ReleaseConfig) -> str:
    """Return the repository and channels as one tab-separated line."""

    return f"{config.image_repository}\t{' '.join(config.channels)}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the Armada fork release metadata"
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, metavar="PATH")
    parser.add_argument(
        "--reference",
        metavar="REF",
        help=argparse.SUPPRESS,
    )
    arguments = parser.parse_args(argv)

    if arguments.reference is not None:
        try:
            reference = parse_image_reference(arguments.reference)
        except ReleaseConfigError as error:
            print(f"armada-release-config: {error}", file=sys.stderr)
            return 1
        print(reference.repository)
        return 0

    try:
        config = load_release_config(arguments.config)
    except ReleaseConfigError as error:
        print(f"armada-release-config: {error}", file=sys.stderr)
        return 1

    print(shell_line(config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
