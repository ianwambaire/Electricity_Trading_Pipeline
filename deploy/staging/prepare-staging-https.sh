#!/usr/bin/env bash
# Approval required: staging-only ACME issuance and renewal preparation.
# Execute once through reviewed bounded SSH stdin; no automatic rollback/retry.
set -euo pipefail
umask 077
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

ACME_EMAIL='iannganga11079@gmail.com'
[[ "$ACME_EMAIL" == *@* ]]

STATE=/var/lib/powerflow-staging-https-20261026
WEBROOT=/var/www/powerflow-staging-acme
CONF=/etc/nginx/conf.d/powerflow-staging-acme.conf
CERTDIR=/etc/letsencrypt-powerflow-staging
WORKDIR=/var/lib/letsencrypt-powerflow-staging
LOGDIR=/var/log/letsencrypt-powerflow-staging
LIVE="$CERTDIR/live/staging.powerflowenergy.dev"

# All production-path checks and baseline reads precede payload writes,
# including nginx -t, which may itself open/create configured log files.
[[ $EUID -eq 0 ]]
for tool in \
  /usr/sbin/nginx \
  /usr/bin/certbot \
  /usr/bin/systemctl \
  /usr/bin/systemd-analyze \
  /usr/bin/openssl \
  /usr/bin/curl \
  /usr/bin/timeout \
  /usr/bin/sha256sum \
  /usr/bin/install \
  /usr/bin/cat \
  /usr/bin/chmod \
  /usr/bin/grep \
  /usr/bin/cmp \
  /usr/bin/python3
do
  [[ -x "$tool" ]]
done

[[ -d /etc/nginx/conf.d && ! -L /etc/nginx/conf.d ]]
[[ -d /var/www && ! -L /var/www ]]
[[ -f /etc/nginx/conf.d/powerflow.conf && ! -L /etc/nginx/conf.d/powerflow.conf ]]
[[ -r /etc/nginx/conf.d/powerflow.conf ]]
[[ -r /etc/letsencrypt/live/powerflowenergy.dev/fullchain.pem ]]
[[ -r /etc/pki/tls/certs/ca-bundle.crt ]]

# Refuse existing files, directories and dangling symlinks.
for path in \
  "$STATE" "$WEBROOT" "$CONF" "$CERTDIR" "$WORKDIR" "$LOGDIR" \
  /etc/systemd/system/powerflow-staging-cert-renew.service \
  /etc/systemd/system/powerflow-staging-cert-renew.timer
do
  [[ ! -e "$path" && ! -L "$path" ]]
done

# Compute baselines in memory BEFORE mkdir/install, redirection or nginx -t.
PRODUCTION_BEFORE=$(sha256sum \
  /etc/nginx/conf.d/powerflow.conf \
  /etc/letsencrypt/live/powerflowenergy.dev/fullchain.pem)

systemctl is-active --quiet nginx.service
systemctl is-active --quiet powerflow-api.service
systemctl is-active --quiet powerflow-streamlit.service

SERVICES_BEFORE=$(systemctl show powerflow-api.service powerflow-streamlit.service \
  --property=Id,MainPID,ActiveState,SubState)

# Existing configuration must pass before any configuration is installed.
timeout --signal=TERM --kill-after=5s 5s nginx -t

install -d -m 700 "$STATE" "$STATE/units"
printf '%s\n' "$PRODUCTION_BEFORE" > "$STATE/production-before.sha256"
printf '%s\n' "$SERVICES_BEFORE" > "$STATE/services-before"
unset PRODUCTION_BEFORE SERVICES_BEFORE

install -d -m 755 \
  "$WEBROOT" \
  "$WEBROOT/.well-known" \
  "$WEBROOT/.well-known/acme-challenge"

install -d -m 700 "$CERTDIR" "$WORKDIR" "$LOGDIR"

# Create only the staging HTTP virtual host. No apex/www edit.
set -o noclobber
cat > "$CONF" <<'NGINX'
server {
    listen 80;
    server_name staging.powerflowenergy.dev;

    access_log off;
    error_log /var/log/nginx/powerflow-staging-acme-error.log crit;

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/powerflow-staging-acme;
        default_type text/plain;
        try_files $uri =404;
    }

    location / {
        return 404;
    }
}
NGINX
set +o noclobber
chmod 644 "$CONF"

sha256sum "$CONF" > "$STATE/staging-http.sha256"

# No reload on failed validation or unexpected Nginx warnings.
timeout --signal=TERM --kill-after=5s 5s nginx -t \
  > "$STATE/nginx-validation.out" \
  2> "$STATE/nginx-validation.err"

if grep -Eqi '\[(warn|error|emerg|alert)\]' \
    "$STATE/nginx-validation.err"; then
  echo 'STOP: Nginx reported an unexpected warning/error.'
  exit 1
fi

timeout --signal=TERM --kill-after=5s 10s systemctl reload nginx

# Verify staging HTTP routing locally, without a DNS query.
printf '%s\n' 'powerflow-staging-acme-preflight' \
  > "$WEBROOT/.well-known/acme-challenge/preflight-probe"
chmod 644 "$WEBROOT/.well-known/acme-challenge/preflight-probe"

curl --fail --silent --show-error \
  --noproxy '*' \
  --connect-timeout 2 --max-time 5 \
  --resolve staging.powerflowenergy.dev:80:127.0.0.1 \
  http://staging.powerflowenergy.dev/.well-known/acme-challenge/preflight-probe \
  > "$STATE/probe-response"

cmp "$WEBROOT/.well-known/acme-challenge/preflight-probe" \
    "$STATE/probe-response"

# Isolated Certbot state and explicit webroot; no production hooks/lineages.
timeout --signal=TERM --kill-after=5s 45s \
  certbot certonly \
  --config /dev/null \
  --config-dir "$CERTDIR" \
  --work-dir "$WORKDIR" \
  --logs-dir "$LOGDIR" \
  --no-directory-hooks \
  --webroot \
  --webroot-path "$WEBROOT" \
  --cert-name staging.powerflowenergy.dev \
  --domain staging.powerflowenergy.dev \
  --email "$ACME_EMAIL" \
  --agree-tos \
  --non-interactive

openssl x509 -in "$LIVE/cert.pem" -noout \
  -checkhost staging.powerflowenergy.dev
openssl x509 -in "$LIVE/cert.pem" -noout -checkend 2592000
openssl verify \
  -CAfile /etc/pki/tls/certs/ca-bundle.crt \
  -untrusted "$LIVE/chain.pem" \
  "$LIVE/cert.pem"

openssl x509 -in "$LIVE/cert.pem" -noout \
  -dates -ext subjectAltName \
  > "$STATE/staging-public-certificate.txt"

python3 - "$STATE/staging-public-certificate.txt" <<'PY'
import re,sys
from pathlib import Path
text=Path(sys.argv[1]).read_text()
assert re.findall(r'DNS:([^,\s]+)',text)==['staging.powerflowenergy.dev']
PY

# Prepare privately. Do NOT install, enable or start either unit.
cat > "$STATE/units/powerflow-staging-cert-renew.service" <<'UNIT'
[Unit]
Description=Renew PowerFlow staging certificate
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/certbot renew --config /dev/null --config-dir /etc/letsencrypt-powerflow-staging --work-dir /var/lib/letsencrypt-powerflow-staging --logs-dir /var/log/letsencrypt-powerflow-staging --no-directory-hooks --cert-name staging.powerflowenergy.dev --non-interactive --deploy-hook "/usr/sbin/nginx -t && /usr/bin/systemctl reload nginx"
TimeoutStartSec=180
UMask=0077
UNIT

cat > "$STATE/units/powerflow-staging-cert-renew.timer" <<'UNIT'
[Unit]
Description=PowerFlow staging certificate renewal schedule

[Timer]
OnCalendar=*-*-* 03,15:00:00
RandomizedDelaySec=15m
Persistent=true
Unit=powerflow-staging-cert-renew.service

[Install]
WantedBy=timers.target
UNIT

systemd-analyze verify \
  "$STATE/units/powerflow-staging-cert-renew.service" \
  "$STATE/units/powerflow-staging-cert-renew.timer"

# Test renewal only. No --run-deploy-hooks, no timer activation.
timeout --signal=TERM --kill-after=5s 45s \
  certbot renew \
  --config /dev/null \
  --config-dir "$CERTDIR" \
  --work-dir "$WORKDIR" \
  --logs-dir "$LOGDIR" \
  --no-directory-hooks \
  --cert-name staging.powerflowenergy.dev \
  --dry-run \
  --non-interactive

sha256sum --check --status "$STATE/production-before.sha256"
systemctl show powerflow-api.service powerflow-streamlit.service \
  --property=Id,MainPID,ActiveState,SubState \
  > "$STATE/services-after"
cmp "$STATE/services-before" "$STATE/services-after"
systemctl is-active --quiet nginx.service

cat "$STATE/staging-public-certificate.txt"
printf '%s\n' \
  'Staging certificate verified.' \
  'Renewal units prepared and validated; NOT installed or enabled.' \
  'React/HTTPS virtual host NOT activated.'

# Failure/rollback policy: stop, retain partial artifacts, never retry/delete.
# Separately approved rollback (root):
# STATE=/var/lib/powerflow-staging-https-20261026
# CONF=/etc/nginx/conf.d/powerflow-staging-acme.conf
# sha256sum --check --status "$STATE/staging-http.sha256"
# [[ ! -e "$STATE/disabled-staging-acme.conf" ]]
# mv "$CONF" "$STATE/disabled-staging-acme.conf"
# if ! timeout --signal=TERM --kill-after=5s 5s nginx -t; then
#   mv "$STATE/disabled-staging-acme.conf" "$CONF"
#   exit 1
# fi
# timeout --signal=TERM --kill-after=5s 10s systemctl reload nginx
# Never delete/revoke certificates or alter any production renewal unit.
