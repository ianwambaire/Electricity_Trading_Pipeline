# PowerFlow staging React acceptance — local standalone Playwright

Prepared locally only. No Chrome launch or staging request has occurred in this
stage. Offline fixture results are not live application evidence. This harness
uses standalone Playwright; it does not call the integrated browser/Work service.
A future real execution requires separate owner authorization.

## Existing tooling and exact scope

No dependency installation, copying or production dependency-graph changes.
The harness reads the existing external playwright-core 1.61.1 installation:

`/Users/iannganga/Desktop/Make-Kenya-Clean/node_modules/playwright-core`

It uses only its matching cached Chrome for Testing 149.0.7827.55, revision 1228:

`/Users/iannganga/Library/Caches/ms-playwright/chromium-1228/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`

Node must be 22.22.0, macOS arm64. bindings.json pins the 106 existing Playwright
files, all 325 regular Chrome bundle files and five framework symlink targets.
Its SHA-256 is `78e8305b92e8ec338f6dc330456ca427b12c5cbeccce9eabfc7e78549ebfaccc`.
These are local reference hashes, not an independent signed package attestation.
No external files are copied or changed. Missing/version-changed/modified files,
added files, unsafe ownership/modes, unexpected links or escapes block execution.
Normal Chrome framework links are accepted only at their exact bound targets
inside the cached bundle. Personal Chrome 157 and personal profiles are not used.
No fallback browser, automatic download, npx or dependency refresh exists.

Checks start at https://staging.powerflowenergy.dev/forecasting, then navigate via
the actual UI to Pipeline Operations. Desktop 1440x900 and mobile-responsive
390x844 use the same browser context and tab, preserving the application's
sessionStorage-based session without reading or exporting it. Mobile checks are
viewport/responsive checks, not iOS/Android or touch/user-agent emulation.

## Commands and owner participation

From the PowerFlow repository root, local-only verification (no import of the
external Playwright library, no browser or network):

```sh
env -i PATH=/usr/bin:/bin /Users/iannganga/.nvm/versions/node/v22.22.0/bin/node frontend/acceptance/run.mjs --check
```

Offline unit tests (mocked browser objects; no Chrome/staging):

```sh
node --test --test-reporter=dot frontend/acceptance/acceptance.test.mjs
```

Preparation validation: 53 offline tests passed, including mocked lifecycle,
owner/session failure, valid/expired/withheld states, exact chart/table matching,
request blocking, response bounds, evidence sanitization and tool-file checks.
Syntax checks passed. The real local --check verified the existing 431 regular
tool/browser files and five expected links with zero browser launches or staging
requests. These results do not establish real browser/session acceptance.

Future launch command, ONLY after separate authorization:

```sh
env -i PATH=/usr/bin:/bin /Users/iannganga/.nvm/versions/node/v22.22.0/bin/node frontend/acceptance/run.mjs --run --owner-assisted-analyst
```

The clean environment prevents inherited debug/proxy/startup settings from
logging authentication traffic or selecting alternate browser behavior. The
runner rejects unexpected environment keys and requires an interactive terminal.
On macOS the only additional permitted key is __CF_USER_TEXT_ENCODING, generated
by CoreFoundation at process initialization even after env -i. This is a
platform-specific runtime exception, not an inherited credential/proxy/debug
allowance. All other unexpected keys still fail CLEAN_ENV_REQUIRED. Its value
is never read or discarded; the browser's explicit child environment is unchanged.
No .env, secret provider, browser profile, cookie or token store is inspected.
Use a terminal visible to the owner. The default/no-argument mode is --check;
--run plus --owner-assisted-analyst are both required to launch.

1. The runner verifies bindings, creates private evidence, and opens a NEW headed
   Chrome for Testing instance and nonpersistent context at Forecast Intelligence.
2. The OWNER clicks Continue to sign in and completes sign-in/MFA in that browser
   with the EXISTING approved native Cognito Analyst test account. The harness
   never fills or reads authentication fields. No password/code/token in chat or
   terminal. No enrollment, recovery, signup, role changes or account changes.
3. When Forecast Intelligence has loaded, type only READY in the terminal.
   The runner additionally requires server GET /api/auth/me to confirm Analyst;
   Admin, absent/failed role or a missing session blocks acceptance. Personal
   identity fields are discarded. Exact account subject is owner-attested, not
   copied/stored/pinned by this harness.
4. The runner reloads the same authenticated tab once and checks desktop, then
   navigates between Forecast Intelligence and Pipeline Operations and repeats at
   mobile width. It never reads storage, saves storageState, seeds data, forces
   publication, changes the clock or calls inference.
5. The owned browser is closed on completion/failure. Owner login is bounded at
   five minutes, browser run at 7.5 minutes, launch/actions at 20 seconds. No launch
   retries. The app's normal read-only refreshes may occur; there is no separate
   backend polling loop. No personal tab is attached, closed or modified.

## Read-only guard and authentication exception

The context blocks application POST/PUT/PATCH/DELETE/OPTIONS and all unapproved
GET endpoints. Exact allowlist covers only reviewed Forecast/Pipeline read APIs,
app routes and local static assets. Historical one-hour requests require exactly
limit=500&offset=0; context requests allow only the issue_time query. No /admin or
/account API, Profile route, export/download, websocket or popup is allowed.
Service workers, downloads, extensions and browser background networking are
blocked/disabled. TLS verification and browser sandboxing remain enabled.

Authentication itself necessarily uses POST. During the owner-only login phase,
the fixed reviewed Cognito hosted origin may handle /login, /mfa, /selectMfa and
/oauth2/token, plus narrow GET login/assets and public issuer discovery/JWKS.
These are the only auth exceptions; application writes remain blocked throughout.
The harness reads NO authentication request headers, form bodies, token responses,
cookies, storage or authentication fields. After READY, auth POSTs are blocked.
No AWS SDK, credential retrieval, user creation, MFA enrollment or recovery is run.
Native Cognito is the supported owner workflow. Google/federated login, new CDN
origins, unknown managed-login paths or an authentication refresh may be blocked.
Such a block requires review; the allowlist never expands automatically.

## What is compared

The observer captures only bounded, identity-encoded responses for /api/auth/me,
/api/forecast/next24 and /api/operations/summary. Require declared Content-Length
<=8 KiB for role or <=256 KiB otherwise, then verify actual bytes. Unknown lengths,
compression, malformed content and oversized responses fail closed. Browser
Accept-Encoding requests identity; that behavior remains untested in real Chrome.
Only the role, selected forecast fields and Operations forecast status survive
projection in memory. All other bodies, identity values and reason strings are
excluded. Normal account JWTs continue to be managed by the app/browser, never
read or constructed by the harness.

For a valid current publication, check 24 finite h+1..h+24 UTC predictions,
expected HGB model release, consistent issue/completion/three-hour cutoff and
no-store. Compare each exact table time/value with its observed API row, hover
all 24 plotted dots and compare tooltip timestamps/values (display precision
three decimals), verify elapsed/future legends and separate historical labels.
Compare issue, completion, cutoff, horizon and future-target facts with the API.
Check one availability banner, visible chart, navigation and no document-wide
horizontal overflow. Intentional table scrolling remains separate from root
layout overflow. Pipeline Operations must display the matching forecast status
and its Analyst restriction, without accessing Admin APIs.

For 503 FORECAST_WITHHELD or an expired response, require WITHHELD and no live
chart, table or forecast statistics. Historical one-hour information may remain
only in its explicitly historical section. Report live rendering NOT_OBSERVED.
A genuine withheld/expired state passing its checks yields overall PARTIAL,
never a claim that live forecasts rendered. Expiry during a comparison yields
an explicit FRESHNESS_BOUNDARY_DURING_CHECK gap, not a fabricated success.
Current UTC timestamps are recorded per check; no time manipulation is used.

PASS requires both viewport sequences and live rendering. FAIL records a proven
contract/layout mismatch or unexpected browser/network errors. BLOCKED records
missing tooling/login or an unapproved prerequisite. PARTIAL records unavailable
live forecasts or a freshness boundary. Role-specific UI and server role are
checked; this is not exhaustive server-side authorization testing. Public APIs
lack receipt/bundle IDs and model file hashes, so this harness does not repeat
remote bundle/pointer integrity verification. Independent backend evidence remains
separate from browser acceptance.

## Private evidence and limits

Outputs are created only under ignored
`data/backups/private-staging-browser-acceptance/acceptance-*`:

- assessment.json: selected enums/counts/timestamps/viewport results only.
- desktop/mobile-responsive availability, forecast (only when valid), Operations
  screenshots. These are scoped to known application panels, excluding account
  headers, not full browser pages. Operations free-text paragraphs/details are
  masked. No auth screenshots, HAR, tracing, video, raw console text, network
  headers, auth URLs/query strings, request bodies, profile files or state dumps.

Require Git-ignore before creating evidence, no symlink parents, owner-only root
and run directories (0700), files 0600. No credentials/raw errors in reports.
Detected sensitive visible UI patterns stop screenshot capture. Such pattern
checks cannot prove absence of every possible information leak; the owner should
review private screenshots. Console/page errors and failed requests are counted,
not persisted as strings; expected forecast 503 and cancelled reads are separate.
The event bound is 500. Browser-level profile files are temporary Playwright-owned
launch artifacts, not a saved authenticated context or reused personal profile.

The browser has NOT been launched in preparation. OS/sandbox compatibility,
Cognito UI resources, actual deployed selectors, real chart tooltips and real
responsive behavior remain unverified until authorized execution. Strict selectors
can identify a deployed UI version difference; do not silently substitute fixture
or historical data. Fixture tests never serve/fulfill browser responses in a real
run. No production files, services, databases, pipeline or model are changed.

## CLEAN_ENV_REQUIRED correction and local key-only diagnosis

The first authorized execution did not launch Chrome. The original guard permitted
only PATH, TMPDIR and LANG, but macOS's CoreFoundation inserts the public runtime
key __CF_USER_TEXT_ENCODING before Node/harness entry. No value was inspected.

Controlled local probes established the boundary:

| Own process started under env -i PATH=/usr/bin:/bin | Observed safe keys |
| --- | --- |
| Native C probe, no CoreFoundation linkage | PATH |
| Same source linked to CoreFoundation (no explicit framework calls) | PATH, __CF_USER_TEXT_ENCODING |
| Bound Node 22.22.0, before harness imports | PATH, __CF_USER_TEXT_ENCODING |
| Harness key-only mode, interactive terminal | PATH, __CF_USER_TEXT_ENCODING |

The bound Node binary's otool -L metadata lists CoreFoundation. Thus env -i is
working; the additional key arises at native framework initialization, before
any harness child, browser, Playwright, sign-in or staging operation. The precise
internal CoreFoundation function was not instrumented. No other process's
/proc, ps environment, browser profile or secret provider is inspected.

The correction is one explicit Darwin-only runtime key in environment.mjs. It
does not permit that key on other platforms, discard variables, read values or
change child-process environments. NODE_OPTIONS, DEBUG, HOME, proxies, credential
keys and every unknown key remain rejected. Existing core/browser/tooling guards,
106 Playwright files, 325 browser files and five expected links remain unchanged.

A local diagnostic option never launches or authenticates:

```sh
env -i PATH=/usr/bin:/bin /Users/iannganga/.nvm/versions/node/v22.22.0/bin/node frontend/acceptance/run.mjs --inspect-environment
```

It returns fixed public key names only, redacts unknown names to a count, verifies
argument/runtime identity metadata, and reports legacyGuardAccepted=false plus
accepted=true for the confirmed macOS startup case. No values, raw command lines,
secret-bearing key names or unrelated process environments are emitted. Extra
CLI arguments are rejected rather than entering the browser path.

```sh
node --test --test-reporter=dot frontend/acceptance/acceptance.test.mjs frontend/acceptance/environment.test.mjs
```

Validation: 72 tests passed (53 original plus 19 environment cases). Tests use
getter traps to prove values are not accessed, reject additional keys, exercise
fixed argv and env -i/explicit-child environments, compile the tiny own-process
native probe twice into temporary local paths, and compare framework-linked and
unlinked entry states. Existing browser/tooling source hashes are checked against
the prior reviewed files. The native probe requires the already installed macOS
Command Line Tools; it does not install anything or invoke a browser/network API.

The future acceptance command above is unchanged. Corrected source must be
manually reviewed/committed and separately authorized before another real run.
No acceptance retry, Chrome launch or staging request occurred during this fix.

## Setup-substep diagnostics (local preparation after the November 4 attempt)

Historical evidence: 2026-11-04 17:58:45–17:59:09 UTC returned
BROWSER_STEP_UNVERIFIED in the coarse BROWSER_LAUNCH phase. Seven monitor events,
zero blocked requests, no sign-in, and no other retained files were available.
That report contains neither a substep nor exception/transport metadata. It cannot
establish the original exception or its cause. Active monitoring narrows the
candidate sequence but is not proof of a particular timeout, TLS or policy fault.
The original assessment is preserved unchanged.

The instrumented sequence is now:

1. LOAD_PLAYWRIGHT (import the checked external library).
2. LAUNCH_BROWSER (same executable/options and 20-second launch bound).
3. INSTALL_BROWSER_MONITOR (disconnection event).
4. CREATE_CONTEXT (same isolated context).
5. CONFIGURE_TIMEOUTS (same 20-second action/navigation limits).
6. CREATE_PAGE.
7. INSTALL_REQUEST_GUARD (same read-only HTTP allowlist).
8. INSTALL_WEBSOCKET_GUARD (same deny policy).
9. INSTALL_EVENT_MONITOR (responses/failures, console, close and other events).
10. INITIAL_NAVIGATION (same /forecasting and waitUntil=domcontentloaded).
11. OWNER_SIGN_IN and VERIFY_ANALYST.
12. ACCEPTANCE_CHECKS, then COMPLETE.

A structured setup field records only step, lastCompleted, category, networkCode,
resource class, main-navigation httpStatus, redirected/closed booleans and a fixed
policy reason. Failed steps are never marked complete. Deliberate browser cleanup
cannot overwrite the failure with a spurious closure or late network event.
Sanitization reconstructs fields from exact enums; no input URL, arbitrary error
name/code, raw message, stack, headers, body or environment is serialized.

Categories distinguish Playwright import, executable launch, context/page creation,
configuration, interception and event-monitor failure; navigation/other Playwright
timeouts; DNS/network/TLS errors; unexpected redirects; request-policy rejection;
staging/authentication document HTTP failure; browser/page closure; rule rejection;
and unknown Playwright exceptions. Only listed Chromium net::ERR_* tokens and
standard closure/timeout patterns are inspected transiently. Unknown error text is
not retained. Public resource classes replace URLs, including authentication URLs
with authorization-code/state query parameters.

During initial navigation, the observer records only main-document HTTP status,
known target class and redirect association, or a fixed main-navigation failure
code. The navigation completion also requires a response, a permitted initial
staging/auth target and a non-error document status. An initial HTML HTTP 503 is
STAGING_HTTP_FAILURE, separate from the existing forecast API 503 withholding
contract. Unknown redirects remain blocked; the code does not follow an expanded
origin allowlist. A first recorded guard failure takes precedence over a later
abort/timeout, so REQUEST_POLICY_REJECTED retains its specific fixed reason.

Policy review found no locally demonstrated mismatch for the initial staging URL,
bundled JS/CSS/fonts, public Cognito issuer metadata or the approved native Cognito
login redirect. The frontend starts sign-in only on the owner's button action.
The public frontend .env.example confirms the same approved hosted origin. No
private .env or authentication data was read. The HTTP policy function remains
byte-identical (SHA-256
3925e4721235642ce04882299f001c21c872952128d5abc1728f9499e9aa736b).
The rejection of unapproved origins, paths, asset queries, account mutations and
non-native authentication remains intentional; a future rejection is evidence to
review, not permission to widen the policy automatically.

Validation: 112 offline tests passed (53 acceptance, 19 environment, 40 setup).
Setup mocks fail each operation once, retain its last completed step and verify
single launch/no retry. Cases cover transport/TLS tokens, navigation timeout,
closures, document HTTP 503, allowed Cognito redirect, blocked foreign redirect,
policy-vs-timeout precedence, observer errors, server role failure and unknown
errors containing synthetic private URLs/tokens. Tests verify redaction and the
unchanged read-only policy, environment guard and tool bindings. Only mock browser
objects and local fixtures are used; existing native environment fixtures launch
no browser and make no network requests. Actual live cause remains UNVERIFIED.

```sh
node --test --test-reporter=dot frontend/acceptance/acceptance.test.mjs frontend/acceptance/environment.test.mjs frontend/acceptance/setup.test.mjs
```

The future launch command and all authentication, resource, evidence and timeout
restrictions are unchanged. Manual review/commit and a new explicit one-attempt
authorization are required before execution. No browser retry, staging request or
source-policy workaround was performed during this preparation.

## Operational-current acceptance (V5 staging)

This focused mode tests Executive Overview and Pipeline Operations at 1440×900
and 390×844. Admin additionally verifies the normal authenticated
`/api/admin/operations/current` response and masks association identifiers in
screenshots. Analyst verifies the server-reported role and absence of the Admin
association panel. It does **not** claim a live authenticated Analyst HTTP 403:
the UI makes no such request, and the harness never extracts/replays tokens.
Public `/api/operations/current` and `/api/pipeline/current` responses must match;
the application's strict parser rejects Admin fields in public data. Current
records must agree across both pages and viewports. A publication change during
checks stops the comparison rather than mixing versions. VALID is not evidence
of a live next24 forecast; that remains a separate acceptance condition.

Run each role in a separate invocation/fresh isolated browser context:

```sh
env -i PATH=/usr/bin:/bin /Users/iannganga/.nvm/versions/node/v22.22.0/bin/node frontend/acceptance/run.mjs --run --operations --owner-assisted-admin
env -i PATH=/usr/bin:/bin /Users/iannganga/.nvm/versions/node/v22.22.0/bin/node frontend/acceptance/run.mjs --run --operations --owner-assisted-analyst
```

The owner explicitly requires Google federation. This mode alone permits the
Google accounts HTTPS sign-in/OAuth paths and narrowly scoped login assets during
owner-assisted login, plus Cognito's `/oauth2/idpresponse`. The default forecast
mode's native-only policy remains unchanged. Google account management, recovery,
enrollment, unrelated origins and staging mutations remain blocked. No auth
request/response content, credentials, headers, cookies, storage or profiles are
read or retained. An unapproved resource fails closed; there is no automatic
policy widening or browser retry. The owner types READY only after sign-in.

Authentication origin reference: Google OIDC discovery
https://accounts.google.com/.well-known/openid-configuration and AWS Cognito social
IdP documentation; the existing application identifies Google federation.
No change to Cognito, users, roles or application authentication is involved.

Sanitized assessment and scoped screenshots remain under the private Git-ignored
`data/backups/private-staging-browser-acceptance/` directory. Missing/stale/invalid
records are tested honestly; current operational acceptance stays PARTIAL unless
VALID is genuinely observed. Console/network counts are reported independently,
including unavailable historical reports. No historical snapshot substitutes for
current execution evidence. Run offline checks with:

```sh
/Users/iannganga/.nvm/versions/node/v22.22.0/bin/node --test frontend/acceptance/*.test.mjs
```
