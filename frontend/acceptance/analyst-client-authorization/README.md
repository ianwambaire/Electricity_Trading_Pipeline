# Direct existing-client Analyst check — local preparation only

No live/browser execution in this milestone. Retarget-based check is retired for
this procedure; its null/null/FAIL result was blocked before identity acceptance,
not evidence that the application granted Analyst access to Admin data.

The exact V2 deployed main module exports the existing API object as `g` and
ApiError as `h`. BINDINGS.json derives its hash from the unchanged approved V2
release manifest and trusted local static bytes. The direct core imports the
same URL (no query/cache busting) and calls currentAdminOperations() once. It does
not patch fetch, rewrite requests, import an alternate auth client, read tokens,
headers/cookies/storage, change role, or modify any deployed asset.

The future runner must reuse existing isolated Chrome tooling, owner-assisted
managed login and normal server identity verification. Prefer the previously
verified native Analyst test identity if the owner still controls it; a Google
identity cannot be substituted with a password flow. Do not create or relink users.
The owner alone submits credentials and any MFA code. This proposal does not
assume that prior account state or current sign-in capability is unchanged.

Before direct invocation: observe the main HTML/script response, require its
exact existing release binding, confirm actual server /api/auth/me role Analyst
and matching application role. Only then arm the one-shot request observer.
Passive response observation consumes only the fixed Admin response (JSON,
identity encoding, declared/exact length<=4096). PASS requires actual403 and only
{"detail":"Administrator permission is required."}; unrecognized fields fail.
The request guard remains read-only and must abort duplicate/direct-before-armed,
redirected, mutating or unrelated requests. Never inspect authorization headers.

Output only httpStatus/adminDataDisclosed/result; preserve separate sanitized
BLOCKED stage if browser/identity preconditions fail so a harness crash is not
misreported as failed server authorization. Close fresh context/browser on every
exit; no authenticated storageState/HAR/traces/raw errors are retained. No retry.

Offline tests use a mock ESM namespace and existing real contract fixtures;
they do not prove genuine Analyst acceptance. VM-module flags are test-only,
not a browser/runtime dependency or a change to production security.

Tests:
/Users/iannganga/.nvm/versions/node/v22.22.0/bin/node --experimental-vm-modules --test frontend/acceptance/analyst-client-authorization/core.test.mjs

The integrated run.mjs verifies the exact HTML/main-module response hashes, loaded
module URL, server-reported Analyst role and displayed role before invoking the
client. Mocked lifecycle tests verify single-request execution, blocked identity/
bundle/crash paths and context/browser cleanup. Unlike the previous runner,
blocked setup has a fixed stage and is not presented as failed authorization.

The immutable MANIFEST.json binds this companion and its full local import/tooling
closure. checkTooling verifies the external Playwright/Chrome trees. No personal
profile, credentials, cookie/storage reads or saved authenticated state.

Local-only command (does not launch Chrome or contact staging):
env -i PATH=/usr/bin:/bin /Users/iannganga/.nvm/versions/node/v22.22.0/bin/node frontend/acceptance/analyst-client-authorization/run.mjs --local-check --manifest-sha256 HASH

Future command, separate owner authorization required:
env -i PATH=/usr/bin:/bin /Users/iannganga/.nvm/versions/node/v22.22.0/bin/node frontend/acceptance/analyst-client-authorization/run.mjs --run --manifest-sha256 HASH

No live invocation was performed during local integration. Browser 420s total,
login300s, request20s, no retries. Restore request guard before closing the fresh
context/browser. No request retargeting or response replacement is used.
