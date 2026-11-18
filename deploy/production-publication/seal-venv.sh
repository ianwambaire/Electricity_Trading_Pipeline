#!/bin/bash
set -euo pipefail

# Run after installing the pinned environment into a new immutable release.
venv=${1:?Pass the new release venv directory}
test "${venv##*/}" = venv
test -d "$venv"
test ! -L "$venv"
test -x "$venv/bin/python"
test -f "$venv/pyvenv.cfg"
chown -hR root:powerflow-api -- "$venv"
chmod -R u=rwX,g=rX,o= -- "$venv"
