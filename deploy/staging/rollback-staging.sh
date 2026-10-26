#!/usr/bin/env bash
# PROPOSAL ONLY: removes only this staging virtual host, never the apex config.
set -euo pipefail
umask 077
[[ $# == 1 && "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$ ]] || exit 64
state="/var/lib/powerflow-staging/$1"
[[ -d "$state" && ! -L "$state" ]] || exit 65
[[ -f /etc/nginx/conf.d/powerflow-staging.conf ]] || exit 66
[[ ! -e "$state/disabled-staging.conf" ]] || exit 67
mv /etc/nginx/conf.d/powerflow-staging.conf "$state/disabled-staging.conf"
# Preserve all artifacts. On validation failure move the file back; no reload occurs.
if ! nginx -t; then
  mv "$state/disabled-staging.conf" /etc/nginx/conf.d/powerflow-staging.conf
  exit 68
fi
systemctl reload nginx
systemctl stop powerflow-candidate-api.service
# Static symlink is no longer served. Old API and Streamlit remain unchanged.
printf '%s\n' 'Staging disabled; release, previous link record and config retained.'
