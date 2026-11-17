# One-shot genuine Analyst authorization acceptance

Test-only companion. No application changes or DevTools instrumentation.
Reuse pinned Playwright/Chrome verification, isolated launch/context, strict clean
environment, reviewed Google/Cognito owner-assisted login policy and READY prompt.
Server GET /api/auth/me must return Analyst, fresh within90s, before arming.
The owner alone enters credentials in the browser. Never inspect auth requests,
request headers, request bodies, cookies or storage. No personal profiles reused.

Only one application-generated GET /api/operations/current (button Refresh current
execution on Pipeline Operations) is continued with the fixed same-origin URL
/api/admin/operations/current. Browser-managed authentication is unchanged; no
header override or token replay by the harness. No new API client/auth source.
Block direct Admin requests, duplicates, redirects, unknown resources and staging
writes. Existing narrowly reviewed owner-login POST exceptions remain login-only.
No manual APIs are called outside normal login/identity and the one target probe.

Only 403 with the exact sole JSON field detail='Administrator permission is
required.' establishes no disclosure. Response requires bounded length <=4096,
JSON content type and no compression. Other shapes/statuses fail. Output only
httpStatus, adminDataDisclosed and result. Never raw bodies, exception text, HAR,
trace, screenshots, tokens or identity details. Restore routes and close the
fresh context/browser in finally. No saved authenticated state or evidence files.

One invocation, no retries. Total420s, manual login300s, probe20s, browser launch20s.
Initial failures return null/null/FAIL (blocked, not evidence of an authorization
vulnerability). Exact tooling closure and companion manifest verified before
launch. Live execution requires the user's explicit authorization.
