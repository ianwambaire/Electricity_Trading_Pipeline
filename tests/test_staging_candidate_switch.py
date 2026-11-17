"""Run the actual switch logic against offline paths and a deterministic clock."""
import os
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'deploy/staging/switch-candidate.sh'


@pytest.fixture
def switch(tmp_path):
    base = tmp_path / 'powerflow'
    records = tmp_path / 'records'
    records.mkdir()
    old, new = (base / 'releases' / name for name in ('old', 'new'))
    for release in (old, new):
        executable = release / '.venv-api' / 'bin' / 'uvicorn'
        executable.parent.mkdir(parents=True)
        executable.touch()
        executable.chmod(0o750)
    pointer = base / 'react-current'
    pointer.symlink_to(old)
    script = tmp_path / 'switch.sh'
    script.write_text(SCRIPT.read_text().replace('/opt/powerflow', str(base))
                      .replace('/var/lib/powerflow-staging', str(records)))
    harness = tmp_path / 'harness.sh'
    harness.write_text("""
# Unset Bash's special timer so only the mocked sleep advances the clock.
unset SECONDS
SECONDS=0
sleep() { SECONDS=$((SECONDS + $1)); }
timeout() { shift; "$@"; }
mv() {
    test "$1" = -Tf
    "$TEST_PYTHON" -c 'import os,sys; os.replace(sys.argv[1],sys.argv[2])' "$2" "$3"
}
systemctl() {
    case "$1" in
      restart)
        test "$2" = powerflow-candidate-api.service
        echo restart >> "$CALLS"
        if [[ "$SCENARIO" == restart-error ]]; then return 5; fi
        ;;
      is-active)
        test "$*" = 'is-active --quiet powerflow-candidate-api.service'
        [[ "$SCENARIO" != inactive ]]
        ;;
      show) printf 'ActiveState=failed\nResult=exit-code\n' ;;
      *) return 99 ;;
    esac
}
curl() {
    local url="${@: -1}"
    case "$url" in
      http://127.0.0.1:8010/health|http://127.0.0.1:8010/ready) ;;
      *) return 99 ;;
    esac
    printf '%s %s\n' "$SECONDS" "${url##*/}" >> "$CALLS"
    if [[ "$SCENARIO" == delayed ]] && ((SECONDS < 3)); then
        printf 000
        return 7
    fi
    if [[ "$SCENARIO" == unready && "$url" == */ready ]]; then
        printf 503
        return 22
    fi
    printf 200
}
""")
    calls = tmp_path / 'calls'

    def run(target, transaction, scenario):
        import sys

        result = subprocess.run(
            ['bash', str(script), target, transaction],
            env={**os.environ, 'BASH_ENV': str(harness), 'SCENARIO': scenario,
                 'CALLS': str(calls), 'TEST_PYTHON': sys.executable},
            capture_output=True, text=True, timeout=10,
        )
        return result, calls.read_text().splitlines()

    return run, pointer, old, new, records


def test_waits_through_connection_refused(switch):
    run, pointer, old, new, records = switch
    result, calls = run('new', 'activate', 'delayed')
    assert result.returncode == 0, result.stderr
    assert calls == ['restart', '0 health', '1 health', '2 health', '3 health', '3 ready']
    assert pointer.resolve() == new
    assert (records / 'api-activate' / 'previous-api').read_text().strip() == str(old)


def test_permanent_startup_failure_times_out_without_http_probes(switch):
    run, pointer, _, new, _ = switch
    result, calls = run('new', 'activate', 'inactive')
    assert result.returncode == 124
    assert calls == ['restart']
    assert 'within 60 seconds' in result.stderr
    assert 'ActiveState=failed' in result.stderr
    assert pointer.resolve() == new  # Explicit rollback is still required.


def test_active_but_unready_times_out_and_reports_http_failure(switch):
    run, _, _, _, _ = switch
    result, calls = run('new', 'activate', 'unready')
    assert result.returncode == 124
    assert calls.count('restart') == 1
    assert calls[-2:] == ['59 health', '59 ready']
    assert '/ready: curl exit 22 (HTTP 503)' in result.stderr


def test_rollback_waits_for_the_previous_release(switch):
    run, pointer, old, new, records = switch
    assert run('new', 'activate', 'unready')[0].returncode == 124
    result, calls = run('old', 'rollback', 'delayed')
    assert result.returncode == 0, result.stderr
    assert calls[-6:] == ['restart', '0 health', '1 health', '2 health', '3 health', '3 ready']
    assert pointer.resolve() == old
    assert (records / 'api-rollback' / 'previous-api').read_text().strip() == str(new)


def test_restart_error_preserves_systemctl_exit_code(switch):
    run, _, _, _, _ = switch
    result, calls = run('new', 'activate', 'restart-error')
    assert result.returncode == 5
    assert calls == ['restart']
