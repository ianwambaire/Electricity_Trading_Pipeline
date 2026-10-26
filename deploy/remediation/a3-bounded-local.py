#!/usr/bin/env python3
"""Local-only 180s supervisor; TERM process group, then KILL after five seconds.

No retries or artifact cleanup. Child stdout/stderr inherit the approved private
capture destination. Intended only for separately reviewed A3 command vectors.
"""
import os
import signal
import subprocess
import sys


def run(command, seconds=180, grace=5):
    process = subprocess.Popen(command, start_new_session=True)
    try:
        return process.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
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
