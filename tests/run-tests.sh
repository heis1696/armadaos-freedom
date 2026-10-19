#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

usage() {
    cat >&2 <<'EOF'
Usage: bash tests/run-tests.sh {linux|python|device|root|disk|gui|ostree}
EOF
    exit 2
}

require_commands() {
    local command_name
    for command_name in "$@"; do
        command -v "$command_name" >/dev/null || {
            printf 'Missing required command: %s\n' "$command_name" >&2
            exit 2
        }
    done
}

run_python_tests() {
    local skip_wrapped="${1:-false}"
    local test_file
    local count=0
    shopt -s nullglob
    for test_file in tests/*-test.py; do
        case "$(basename "$test_file")" in
            armada-steam-test.py|armada-tools-ui-test.py|installer-disk-test.py|installer-gui-test.py|installer-source-test.py|waydroid-input-test.py)
                continue
                ;;
        esac
        if [[ "$skip_wrapped" == true && -f "${test_file%.py}.sh" ]]; then
            printf 'Skipping Python test already run by shell wrapper: %s\n' "$test_file"
            continue
        fi
        printf 'Running Python test: %s\n' "$test_file"
        python3 "$test_file"
        count=$((count + 1))
    done
    for test_file in devices/lenovo-tb323fu/tests/test_*.py; do
        printf 'Running Python test: %s\n' "$test_file"
        python3 "$test_file"
        count=$((count + 1))
    done
    printf 'Running Python test: tests/test_g9_double_home.py\n'
    python3 tests/test_g9_double_home.py
    count=$((count + 1))
    printf 'Completed %d Python test files.\n' "$count"
}

run_device_speaker_test() {
    local source="$ROOT/devices/lenovo-tb323fu/rootfs/usr/libexec/tb323fu/tb323fu-speaker-gain"
    require_commands sh mktemp
    DEVICE_TEST_TMP="$(mktemp -d)"
    trap 'rm -rf "$DEVICE_TEST_TMP"' EXIT
    printf 'Running shell test: devices/lenovo-tb323fu/tests/test-tb323fu-speaker-gain.sh\n'
    sh devices/lenovo-tb323fu/tests/test-tb323fu-speaker-gain.sh \
        "$source" "$DEVICE_TEST_TMP/output"
}

run_device_tests() {
    require_commands python3
    printf 'Running Python test: devices/lenovo-tb323fu/tests/test_y700_runtime_record.py\n'
    python3 devices/lenovo-tb323fu/tests/test_y700_runtime_record.py
    printf 'Running Python test: devices/lenovo-tb323fu/tests/test_tb323fu_usb_port.py\n'
    python3 devices/lenovo-tb323fu/tests/test_tb323fu_usb_port.py
    run_device_speaker_test
}

run_linux_tests() {
    local test_file
    local count=0
    require_commands bash python3 jq
    shopt -s nullglob
    for test_file in tests/*-test.sh; do
        # Device-node creation needs root; it has its own explicit entry.
        [[ "$(basename "$test_file")" == waydroid-input-test.sh ]] && continue
        printf 'Running shell test: %s\n' "$test_file"
        bash "$test_file"
        count=$((count + 1))
    done
    run_device_speaker_test
    count=$((count + 1))
    printf 'Completed %d shell test files.\n' "$count"
    run_python_tests true
    printf '%s\n' \
        'Special suites not run by the Linux default: root (just test-root), disk (just test-installer-disk), GUI (just test-installer-gui), OSTree (just test-ostree).'
}

case "${1:-}" in
    linux)
        run_linux_tests
        ;;
    python)
        require_commands python3
        run_python_tests
        ;;
    device)
        run_device_tests
        ;;
    root)
        require_commands python3
        if (( EUID != 0 )); then
            echo 'This suite requires root; use sudo.' >&2
            exit 2
        fi
        bash tests/waydroid-input-test.sh
        ;;
    disk)
        require_commands python3 sgdisk
        python3 tests/installer-disk-test.py
        ;;
    gui)
        require_commands python3 xvfb-run
        python3 -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")'
        xvfb-run -a python3 tests/armada-tools-ui-test.py
        xvfb-run -a python3 tests/installer-gui-test.py
        ;;
    ostree)
        require_commands python3 ostree bootc
        if (( EUID != 0 )); then
            echo 'The installer source suite requires root inside a disposable Armada container.' >&2
            exit 2
        fi
        python3 -c 'import gi; gi.require_version("OSTree", "1.0")'
        python3 tests/armada-steam-test.py
        python3 tests/installer-source-test.py
        ;;
    *)
        usage
        ;;
esac
