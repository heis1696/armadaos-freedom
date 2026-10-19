# Installer device compatibility

The installer currently has a narrow refusal guard for the Lenovo Legion Y700
TB323FU and Y700 AI Infinite 5G TB324ZC. Neither has passed whole-device
installation validation with the generic installer.

Before disk discovery, `gui`, `detect`, and `install` read the running kernel's
`/sys/firmware/devicetree/base/model` and `compatible` files. Matching is exact:

- Model: `Lenovo Legion Y700 Gen 5 (TB323FU)`,
  `Lenovo Legion Tab Y700 (TB323FU)`, or
  `Lenovo Legion Tab Y700 5th Gen`.
- Model: `Lenovo Legion Y700 AI Infinite 5G (TB324ZC)`.
- Any NUL-delimited compatible entry: `lenovo,baldur` or `lenovo,wuji`.

Either a matching model or a matching compatible entry blocks the operation.
This intentionally treats conflicting model and board strings as a refusal.
Missing, empty, malformed, or unreadable identity data also blocks GUI,
detection, and installation before disk discovery. `ARMADA_MODEL`,
`ARMADA_INTERNAL_DEVICE`, `--device`, and `-y` do not supply or override the
device-tree identity.

This is a refusal guard for these known unsupported targets, not a supported
device allowlist or a statement that other devices are compatible. A complete
device, image, partition-layout, and boot-format compatibility contract still
requires validation for each device. No hardware or block device is used by the
installer protection tests; they exercise the CLI entry point with a temporary
device-tree directory and mocked disk commands. On Ubuntu WSL, run
`python3 tests/installer-test.py`.
