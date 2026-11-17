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
unit=powerflow-candidate-api.service
systemctl restart "$unit"

deadline=$((SECONDS + 60))
last_probe='service not active'
probe() {
    local path=$1 remaining status
    remaining=$((deadline - SECONDS))
    if ((remaining <= 0)); then
        last_probe="/$path: deadline reached"
        return 1
    fi
    if ((remaining > 2)); then remaining=2; fi
    if status=$(curl --fail --silent --noproxy '*' --max-time "$remaining" \
        --output /dev/null --write-out '%{http_code}' "http://127.0.0.1:8010/$path"); then
        last_probe="/$path: HTTP $status"
        [[ "$status" == 200 ]]
    else
        last_probe="/$path: curl exit $? (HTTP ${status:-000})"
        return 1
    fi
}

while ((SECONDS < deadline)); do
    if timeout 1s systemctl is-active --quiet "$unit"; then
        if probe health && probe ready; then
            printf '%s is active; health and readiness returned HTTP 200.\n' "$unit"
            exit 0
        fi
    else
        last_probe='service not active or status unavailable'
    fi
    if ((SECONDS < deadline)); then sleep 1; fi
done

# Keep the record and target pointer for explicit rollback. Never restart again here.
printf 'Staging API did not become ready within 60 seconds for %s (%s). Previous target recorded in %s.\n' \
    "$next" "$last_probe" "$record/previous-api" >&2
timeout 5s systemctl show "$unit" -p ActiveState -p SubState -p Result -p MainPID >&2 || true
exit 124
# Rollback: invoke this script again with recorded previous release basename and
# a NEW record ID, under separate explicit approval. Never replace the old8000.
