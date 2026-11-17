# Staging React404 — read-only diagnosis

One authorized bounded SSH inspection exited0. No remote files/permissions/configuration changed, no service operation, no native nginx -t/-T and no reload occurred. Normal read-only HTTP probes can generate access logs. Evidence: `REACT-404-DIAGNOSTIC-RESULTS.json`; private captures `/private/tmp/powerflow-react-404-diagnostic-3smnijbf/`.

## Verified results

- Public and loopback HTTPS `/` and loopback `/index.html`:200,748bytes, SHA256 `0f279d5d2e94de494ff56050c46034822aba1bb03a46bec915c7ac3bdecafad9`, matching the immutable release index.
- Three index-referenced assets (main JS, CSS, JSX runtime):200; every response hash matches the immutable release. Nginx worker's effective UID can traverse all static parents and read these files. Current symlink points to the expected release. No permission or missing-file fault found.
- Staging is the unique HTTPS server_name on443 from `/etc/nginx/conf.d/powerflow-staging-https.conf`. Root `/var/www/powerflow-staging/current`; index index.html; location `/` try_files `$uri $uri/ /index.html`; `/api/` proxies to127.0.0.1:8010. Reviewed config hash matches. Corrected strict include/server-conflict review passes.
- Proxied HTTPS `/api/health`:200. Candidate direct `/health` and `/ready`:200.
- Plain HTTP80 `/` returns404 intentionally: the staging HTTP virtual host is ACME-only. It does not indicate broken HTTPS routing.
- Production API/Streamlit/Prefect worker/server/PostgreSQL identities match original saved baselines. Production vhost, public certificate and staging ACME configuration hashes unchanged.

## Cause and minimal correction

The previous HTTPS404 does not reproduce; there is no currently failing static file or Nginx directive. The failed activation sent one immediate request just after systemctl reload returned. An old worker serving the prior intentional404 during asynchronous graceful reload is a plausible cause, **not proven by the retained evidence**. The current index/asset hashes and API response establish that staging routing is now effective.

No remote correction or additional reload is needed. Local-only `continue-r2-activation.py` now uses bounded10-second root readiness probes after reload instead of a single immediate check: tolerate only transitional404, require exact approved index hash on200, reject wrong200/other statuses immediately. Certificate verification stays unchanged. No repeated reload, restart, configuration rewrite or deployment retry. This change was NOT executed remotely and the existing continuation attempt markers are not bypassed.

Updated local continuation SHA256 `956bdcf4182e8bee64e154636d7393f4188b59951d401dfd205aec080dc14070`.

79 targeted tests passed, including404→correct200, persistent404 deadline, immediate500 failure and wrong-content200 failure. Existing parser/include/reload tests remain passing. Native Nginx validation already passed for this unchanged configuration during the authorized activation; it was deliberately not repeated during this strictly read-only diagnosis.

React's HTTPS entry and referenced assets are accessible now. Real Cognito sign-in and authenticated seven-page browser acceptance remain separate; this read-only test did not change Cognito or authenticate users. No Git operations performed.
