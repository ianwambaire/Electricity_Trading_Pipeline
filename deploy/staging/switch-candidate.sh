#!/usr/bin/env bash
# Reviewed immutable candidate update/rollback; NEVER changes existing API8000.
set -euo pipefail
umask 077
[[ $# == 2 && "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$ && "$2" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$ ]] || exit 64
next="/opt/powerflow/releases/$1"
record="/var/lib/powerflow-staging/api-$2"
[[ -d "$next" && ! -L "$next" && -x "$next/.venv-api/bin/uvicorn" ]] || exit 65
[[ ! -e "$record" && ! -L "$record" ]] || exit 66
[[ -L /opt/powerflow/react-current ]] || exit 67
previous=$(readlink /opt/powerflow/react-current)
[[ "$previous" =~ ^/opt/powerflow/releases/[A-Za-z0-9._-]+$ && -d "$previous" ]] || exit 68
mkdir -m 700 "$record"
printf '%s\n' "$previous" > "$record/previous-api"
[[ ! -e /opt/powerflow/react-next && ! -L /opt/powerflow/react-next ]] || exit 69
ln -s "$next" /opt/powerflow/react-next
mv -Tf /opt/powerflow/react-next /opt/powerflow/react-current
systemctl restart powerflow-candidate-api.service
# No automatic retry or automatic rollback. Keep failure evidence for owner.
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8010/health > /dev/null
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8010/ready > /dev/null
# Rollback: invoke this script again with recorded previous release basename and
# a NEW record ID, under separate explicit approval. Never replace the old8000.
