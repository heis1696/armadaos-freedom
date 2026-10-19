#!/usr/bin/env python3
"""Validate `cosign verify` output against the exact release identity+digest.

`cosign verify --key <pub> <repo>@<digest>` proves only that the signature was
made by <pub> over a payload claiming <digest>: key-based verification does not
compare the repository name inside the signed payload with the repository in
the ref, so a signature on one repository can satisfy a check on another. The
client closes this gap with policy.json signedIdentity exactRepository; CI
self-verification (build.yml) and promotion (promote.yml) close it with this
helper: it fails closed unless the verified signature list is non-empty and at
least one signature carries critical.identity.docker-reference == --identity
AND critical.image["docker-manifest-digest"] == --digest.

Usage: cosign verify ... | verify-signature-result.py --identity REPO --digest sha256:...
"""

import argparse
import json
import sys
from pathlib import Path

IDENTITY_FIELD = ("critical", "identity", "docker-reference")
DIGEST_FIELD = ("critical", "image", "docker-manifest-digest")


def fail(message: str) -> int:
    print(f"verify-signature-result: error: {message}", file=sys.stderr)
    return 1


def read_field(signature, path):
    value = signature
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--identity",
        required=True,
        help="expected critical.identity.docker-reference (bare repository, no tag/digest)",
    )
    parser.add_argument(
        "--digest",
        required=True,
        help="expected critical.image.docker-manifest-digest (sha256:...)",
    )
    parser.add_argument(
        "input",
        nargs="?",
        help="cosign verify JSON output (default: stdin)",
    )
    args = parser.parse_args()

    if args.input is None:
        raw = sys.stdin.read()
    else:
        try:
            raw = Path(args.input).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            return fail(f"cannot read cosign verify output: {exc}")

    try:
        verified = json.loads(raw)
    except ValueError as exc:
        return fail(f"cosign verify output is not valid JSON: {exc}")
    if not isinstance(verified, list):
        return fail("cosign verify output is not a JSON array of signatures")
    if not verified:
        return fail("cosign verify returned no signatures (empty result)")

    checked = []
    for signature in verified:
        identity = read_field(signature, IDENTITY_FIELD)
        digest = read_field(signature, DIGEST_FIELD)
        if identity == args.identity and digest == args.digest:
            print(
                "verify-signature-result: verified signature matches the release "
                f"identity and digest (identity={args.identity}, digest={args.digest})"
            )
            return 0
        checked.append(f"identity={identity!r} digest={digest!r}")

    return fail(
        f"no verified signature matches identity {args.identity!r} and digest "
        f"{args.digest!r}; checked {len(verified)} signature(s): " + "; ".join(checked)
    )


if __name__ == "__main__":
    sys.exit(main())
