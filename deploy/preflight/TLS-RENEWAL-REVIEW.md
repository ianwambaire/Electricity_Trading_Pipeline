# TLS verification — read-only approval only

Not executed. One strict SSH session using the existing Package B SSH options/host, remote `timeout --signal=TERM --kill-after=5s 30s bash -s`, local180second supervisor. No sudo, Certbot execution, logs, environment, private keys or configuration bodies. Capture full output privately; return unit states and public certificate dates only. Execute this fixed stdin once:

```sh
set -euo pipefail
/usr/bin/systemctl show certbot-renew.timer certbot-renew.service --property=Id,LoadState,ActiveState,SubState,UnitFileState,NextElapseUSecRealtime,LastTriggerUSec,Result
/usr/bin/openssl s_client -connect 127.0.0.1:443 -servername powerflowenergy.dev </dev/null 2>/dev/null | /usr/bin/openssl x509 -noout -dates -ext subjectAltName
```

Public TLS handshake only; this verifies served public certificate, not private-key reads or renewal success. Paths/tool availability and correct renewal service must be confirmed; failure stops without alternate commands. This does not establish renewal command/hook safety. Request separately a narrowly redacted renewal-unit/webroot inspection if timer/service identity remains unclear.

Separate remediation approval: only after the existing renewal service and its hooks/method are reviewed, propose `systemctl enable --now certbot-renew.timer` (if it truly invokes the intended reviewed renewal service). Do not execute Certbot dry-run/issuance blindly: it can write state, contact ACME and invoke hooks. Back up timer enablement state; rollback `systemctl disable --now certbot-renew.timer` only if originally disabled, without deleting certificate material or affecting Nginx. Enabling a timer can immediately run an overdue renewal, so approval must cover that consequence and any verified hook/reload. Stage certificate/DNS issuance is a separate named change; no email/account details invented.
