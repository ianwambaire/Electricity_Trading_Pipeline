#!/usr/bin/env python3
"""Local-only 180s supervisor; TERM process group, then KILL after five seconds.

No retries or artifact cleanup. Child stdout/stderr inherit the approved private
capture destination. Intended only for separately reviewed A3 command vectors.
"""
import os
import signal
import subprocess
import sys
import time


def run(command, seconds=180, grace=5):
    process = subprocess.Popen(command, start_new_session=True)
    try:
        return process.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        grace_started = time.monotonic()
        try:
            process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            pass
        # A leader can exit while its SCP/SSH descendants remain alive.
        # Give the entire group its grace interval, then kill any survivors.
        remaining = grace - (time.monotonic() - grace_started)
        if remaining > 0:
            time.sleep(remaining)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        return 124


if __name__ == '__main__':
    if len(sys.argv) < 3 or sys.argv[1] != '--':
        raise SystemExit('usage: a3-bounded-local.py -- APPROVED_COMMAND ARG...')
    raise SystemExit(run(sys.argv[2:]))
