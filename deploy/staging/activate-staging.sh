#!/usr/bin/env bash
# PROPOSAL ONLY. Requires separately approved root installation window.
set -euo pipefail
umask 077
[[ $# == 1 && "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$ ]] || exit 64
release="$1"
base=/var/www/powerflow-staging
candidate="$base/releases/$release"
state="/var/lib/powerflow-staging/$release"
[[ -d "$candidate" && ! -L "$candidate" && -f "$candidate/index.html" ]] || exit 65
[[ ! -e "$state" && ! -L "$state" ]] || exit 66
# Installation of static/backend releases, dedicated user, publication, environment,
# certificates and safe-log includes are distinct approved prerequisites.
[[ -L "$base/current" || ! -e "$base/current" ]] || exit 67
# Guard before any configuration writes: capacity is a prerequisite, not proof of peak safety.
awk '/^MemAvailable:/ {ok=($2 >= 786432)} END {exit !ok}' /proc/meminfo
[[ $(df -Pk /var/www/powerflow-staging | awk 'END {print $4}') -ge 2097152 ]] || exit 70
[[ ! -e "$base/current.new" && ! -L "$base/current.new" ]] || exit 71
# Replace only the exact verified staging placeholder, never add a duplicate vhost.
conf=/etc/nginx/conf.d/powerflow-staging-https.conf
[[ -f "$conf" && ! -L "$conf" ]] || exit 68
[[ $(sha256sum "$conf" | awk '{print $1}') == 85ad4c7ec303b638033831cb7ebfd5b73b669c80b249926c8e1446ba70124396 ]] || exit 68
[[ ! -e /etc/nginx/conf.d/powerflow-staging.conf && ! -L /etc/nginx/conf.d/powerflow-staging.conf ]] || exit 68
[[ $(systemctl show powerflow-candidate-api.service --property=ActiveState --value) == inactive ]] || exit 73
nginx -t
mkdir -m 700 "$state"
cp --no-clobber "$conf" "$state/previous-https.conf"
sha256sum deploy/staging/staging.powerflowenergy.dev.conf | awk '{print $1}' > "$state/installed-https.sha256"
if [[ -L "$base/current" ]]; then readlink "$base/current" > "$state/previous-static"; fi
install -m 644 deploy/staging/staging.powerflowenergy.dev.conf "$conf"
ln -s "$candidate" "$base/current.new"
mv -Tf "$base/current.new" "$base/current"
# No restart/reload of the old API or Streamlit.
if ! nginx -t; then
  echo 'STOP: configuration not activated; preserve artifacts, use reviewed rollback.' >&2
  exit 69
fi
systemctl start powerflow-candidate-api.service
# Explicit bounded readiness polling: at most20 read-only requests, no service retries.
ready=false
for attempt in {1..20}; do
  if curl --fail --silent --max-time 2 http://127.0.0.1:8010/ready > /dev/null; then ready=true; break; fi
  sleep 1
done
[[ "$ready" == true ]] || { echo 'STOP: candidate not ready; Nginx not reloaded.' >&2; exit 72; }
systemctl reload nginx
printf '%s\n' 'Staging activated; real-account acceptance still required.'
