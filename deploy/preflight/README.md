# Phase 5D.1 proposals — never installed automatically

These are review artifacts, not an approved deployment or a drop-in replacement.
See `frontend/docs/phase5d1-staging-preflight-and-approval.md` for gates and rollback.

- `nginx-http.conf`: include in the existing `http` context, after checking conflicts.
- `security-headers.conf`: proposed `/etc/nginx/powerflow/` include; inherited headers
  must be repeated wherever `add_header` is set.
- `powerflowenergy.dev.conf`: final-domain routing proposal. Verify certificate paths,
  existing ACME handling, existing locations and consumers before preparing the final diff.
- `powerflow-react-api.service`: separate candidate identity/unit/loopback port8010.
  Do not replace the existing port8000 unit. Port8010 availability and Linux directives
  must be verified. Caps are hypotheses, not measured reservations or capacity proof.
- `api.env.example`: non-secret production example; bind only the approved new SPA ID.
- `cognito-production-client.json`: proposed NEW client, not an update of either existing
  client or pool. No CLI create/update operation was executed. PKCE is enforced by the
  OIDC browser library; client configuration restricts OAuth to authorization code.

Run an isolated Linux `nginx -t` and `systemd-analyze verify` against the assembled
configuration/artifact. Local static guardrail tests do NOT parse Nginx/systemd syntax.
No native Nginx binary or running Docker engine was available for syntax testing here.
No package installation or Docker start was attempted. Do not reload production until
syntax, certificate, callback, proxy, data, role and rollback checks have passed.
