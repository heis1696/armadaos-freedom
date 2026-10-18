# Testing

Run repository checks from the repository root. The `just test` recipe retains
the legacy behavior of executing every `tests/*-test.sh` script. The separated
entries below make environment requirements visible and are used by CI.

## Routine checks

`just test-linux` (or `bash tests/run-tests.sh linux`) runs shell tests except
the root-only Waydroid device-node test, then all `tests/*-test.py` files that
do not need a special environment, plus `tests/test_g9_double_home.py`. Python
tests are discovered from the directory, so a new ordinary `*-test.py` suite is
included automatically. The paired `armada-store-download-test.sh` is included
by the retained shell-test glob, and its Python suite by Python discovery.

`just test-python` runs the same ordinary Python group by itself. CI runs the
Linux group in an Ubuntu 24.04 runner. It requires system Bash, Python 3, and
`jq`; it does not require publishing credentials, device hardware, partitions,
or flashing.

## Special environments

These commands are independent of the routine CI result. A missing dependency
or required privilege makes the command fail before running; it is not counted
as a passing test.

| Entry | Tests | Requirements and safety |
| --- | --- | --- |
| `just test-root` | `tests/waydroid-input-test.py` | Run as root. It creates device nodes and a temporary chroot under a temporary directory; it does not use host `/dev` devices. |
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
release or publishing secrets. Linux, root fixture, Control, and Worker checks
are separate jobs. Disk, GUI, and OSTree suites remain explicit local/container
entries and are not represented as CI passes.
