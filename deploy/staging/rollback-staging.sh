#!/usr/bin/env bash
# Explicit approval only. Restore the verified staging HTTPS placeholder; retain artifacts.
set -euo pipefail
umask 077
[[ $# == 1 && "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$ ]] || exit 64
state="/var/lib/powerflow-staging/$1"
conf=/etc/nginx/conf.d/powerflow-staging-https.conf
[[ -d "$state" && ! -L "$state" ]] || exit 65
[[ -f "$conf" && ! -L "$conf" ]] || exit 66
[[ -f "$state/previous-https.conf" && ! -L "$state/previous-https.conf" ]] || exit 66
[[ $(sha256sum "$state/previous-https.conf" | awk '{print $1}') == 85ad4c7ec303b638033831cb7ebfd5b73b669c80b249926c8e1446ba70124396 ]] || exit 66
[[ $(sha256sum "$conf" | awk '{print $1}') == $(cat "$state/installed-https.sha256") ]] || exit 66
[[ ! -e "$state/disabled-staging.conf" && ! -L "$state/disabled-staging.conf" ]] || exit 67
cp --no-clobber "$conf" "$state/disabled-staging.conf"
install -m 644 "$state/previous-https.conf" "$conf"
# Failure leaves retained artifacts; never automatically repair/reload/retry.
nginx -t
systemctl reload nginx
systemctl stop powerflow-candidate-api.service
printf '%s\n' 'Staging placeholder restored; candidate stopped; all artifacts retained.'
