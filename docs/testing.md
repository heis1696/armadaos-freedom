# Testing

Run repository checks from the repository root. `just test` runs the routine
Linux shell and Python suites, including the TB323FU device tests. The separated
entries below make environment requirements visible and are used by CI.

## Routine checks

`just test` (or `bash tests/run-tests.sh linux`) runs every `tests/*-test.sh`
suite except the root-only Waydroid device-node test. It also runs the TB323FU
speaker-gain mock test, ordinary Python suites under `tests/` and
`devices/lenovo-tb323fu/tests/`, and `tests/test_g9_double_home.py`. Python
suites are discovered by glob. During the Linux run, a Python file with a
same-named shell wrapper is run through that wrapper only, avoiding duplicate
execution. `just test-python` runs the Python suites directly, including those
with shell wrappers. New root-level `*-test.sh` and `*-test.py` suites are
included automatically.

The TB323FU speaker-gain test receives the absolute production script path and
a new output directory below a temporary parent. It uses only its local mocks;
it does not access real devices.

`just test-device` runs the two TB323FU Python suites and the speaker-gain mock
test by themselves.

The Linux default prints the root, disk, GUI, and OSTree groups that it leaves
out and names their independent Just entries. CI runs `just test` in an Ubuntu
24.04 runner. It requires system Bash, Python 3, and `jq`; it does not require
publishing credentials, device hardware, partitions, or flashing.

CI pins Just 1.59.0 and checks Justfile formatting. Older Just versions such as
1.21 do not understand the repository's existing group attributes. Use a Linux
checkout with LF line endings; Windows Git CRLF conversion also changes the
extensionless shell helpers invoked by these tests.

## Special environments

These commands are independent of the routine CI result. A missing dependency
or required privilege makes the command fail before running; it is not counted
as a passing test.

| Entry | Tests | Requirements and safety |
| --- | --- | --- |
| `just test-root` | `tests/waydroid-input-test.py` | Run as root with system Python GI/GLib bindings (`python3-gi`, `gir1.2-glib-2.0` on Ubuntu). It creates device nodes and a temporary chroot under a temporary directory; it does not use host `/dev` devices. |
| `just test-installer-disk` | `tests/installer-disk-test.py` | Python 3 and `sgdisk` (`gdisk` package). GPT operations target sparse regular files created in a temporary directory, never block devices. |
| `just test-installer-gui` | `tests/armada-tools-ui-test.py`, `tests/installer-gui-test.py` | Python GI bindings for GTK 4 and libadwaita, plus `xvfb-run` and a virtual display. |
| `just test-ostree` | `tests/armada-steam-test.py`, `tests/installer-source-test.py` | OSTree CLI, bootc with `internals ostree-ext container image` support, Python GI OSTree bindings. `installer-source-test.py` requires root in a disposable Armada container. |

## JavaScript checks

CI runs Control and Worker tests separately on Node.js 22. Each job uses its
project's committed `package-lock.json` with `npm ci`, then runs `npm test`:

```sh
cd decky/armada-control && npm ci && npm test
cd workers/downloads && npm ci && npm test
```

The Store frontend currently has no `test` script; it is not reported as a
tested JavaScript suite.

## CI

`.github/workflows/tests.yml` runs on pull requests to `main` or `staging` and
on manual dispatch. It requests read-only repository contents and does not use
release or publishing secrets. The Linux job invokes the default `just test`;
the root fixture, Control, and Worker checks are separate jobs. Disk, GUI, and
OSTree suites remain explicit local/container entries and are not represented
as CI passes.
