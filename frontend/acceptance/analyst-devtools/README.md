# One-shot Analyst authorization check — manual DevTools Local Override

Preparation is offline only. No browser, staging request, authentication or live
endpoint test was executed. The helper calls the existing private V5 API client;
it never reads request headers, tokens, cookies, OIDC state or other storage keys.

The exact V5 manifest is
`cdd828defc52ea258852b88aa852d1d470ca915d098021d6ff8fd2be9b05223b`.
The entry bundle is `/assets/index-B_Ifb4TY.js`, 383151 bytes, SHA-256
`e5c1053921f36b834a80bd7b73b3fb61f9a77c76de02922a1af877243c736e71`.
Do not apply to another entry bundle or a different deployed release.

## Prepared artifact

Private folder:

```
/Users/iannganga/Desktop/electricity-trading-pipeline/data/backups/private-staging-browser-acceptance/devtools-analyst-v5-HT12lr
```

Select its **overrides** subfolder in Chrome, not the entire project or profile.
The prepared override expires at **2026-11-07 19:05:19 UTC / 22:05:19 Nairobi**.
Its SHA-256 is
`fbef8264d0aef0fbcbd170b7c5cad5b7d00bb4acf98de859f56b0ad276cb12bc`.
Do not reuse or extend the artifact after expiry.

## 1. Verify before overriding

1. In your normal Chrome profile open
   `https://staging.powerflowenergy.dev/pipeline`. Confirm the account shows
   **Analyst**. Leave authentication and profile settings alone.
2. Open DevTools with **Option–Command–I**. Keep **Preserve log** off. Do not
   inspect/copy request headers, export HARs, save responses or take authentication
   screenshots.
3. In **Sources → Overrides**, ensure **Enable Local Overrides** is off before
   the initial verification. If unrelated overrides are already configured, stop
   rather than replace their folder or change another workflow.
4. Open `VERIFY-BEFORE-OVERRIDE.txt` from the private folder in a text editor.
   Paste its complete contents into the **Console** and press Enter. This makes
   only a public, unauthenticated JS-asset GET; it checks the page's module script
   URL and the actual asset SHA-256. Proceed only if it prints **V5_BUNDLE_MATCH**.
   Any mismatch is a stop, not permission to update the expected hash.
5. If Chrome blocks pasting with a security warning, stop; do not disable browser
   protections to complete this procedure.

## 2. Apply the browser-local override

1. In **Sources → Overrides**, click **Select folder for overrides**.
2. In the macOS folder chooser press **Shift–Command–G** and paste:

   ```
   /Users/iannganga/Desktop/electricity-trading-pipeline/data/backups/private-staging-browser-acceptance/devtools-analyst-v5-HT12lr/overrides
   ```

3. Select that folder. Allow DevTools access to **only that folder** when Chrome
   asks. Enable **Local Overrides**. No Chrome profile or authentication files are
   involved.
4. Under Overrides confirm exactly this file:
   `staging.powerflowenergy.dev/assets/index-B_Ifb4TY.js`.
5. Open Network, enable **Disable cache** while DevTools is open, and reload the
   Pipeline Operations page once. Confirm the exact entry bundle shows Chrome's
   purple local-override indicator (or its local-overrides tooltip).
   If it does not, stop: do not run the probe or edit another bundle.
6. Wait until the application again shows **Analyst** and has finished loading.
   The override performs no automatic probe request.

## 3. Run once

Paste the complete contents of `RUN-ONCE.txt` into the Console once. It calls only
the one-shot existing-client wrapper. It does not build headers or read session
credentials. The existing originating-session validation runs before observation.

Expected output:

```json
{"httpStatus":403,"adminDataDisclosed":false,"result":"PASS"}
```

Only this exact result passes. On any FAIL, null field, absent function, loading
error or unexpected status, stop and share only the three-field result. Do not
retry, reset the marker, sign in as Admin, inspect raw bodies or broaden the test.
Chrome may also show its own HTTP-403 resource error; this is not a probe payload.

The bounded reader accepts only the exact public permission error with no extra
fields. It reads at most 4096 bytes with a three-second read deadline; unknown or
unreadable disclosure is `null`, never a false no-disclosure claim. Status 200
always fails. No raw response, error, headers or credentials are logged or saved.

The global wrapper self-removes before the request. A fixed **non-secret**
consumed marker, `powerflow.devtools.analyst-auth-v5.used`, prevents another call
after reload in the same tab. Only that key is accessed; authentication storage is
never inspected. Keep the same tab and do not duplicate it during the procedure.

## 4. Remove completely, even after FAIL

1. Uncheck **Enable Local Overrides**.
2. In Sources remove this override folder from the workspace (right-click its
   folder → **Remove from workspace**, if shown). This revokes this local workflow;
   it does not alter the server.
3. Copy `CLEANUP-AFTER-REMOVAL.txt` to a plain text editor for the next step. In
   Finder delete only the prepared `devtools-analyst-v5-HT12lr` folder. Do not
   delete parent evidence directories or touch your Chrome profile.
4. Reload Pipeline Operations in the same tab. The bundle must no longer show a
   purple local-override indicator.
5. After removal and reload, paste the saved cleanup code into the Console.
   It rechecks the original public bundle hash and absence of the wrapper, then
   removes only the non-secret consumed marker. Expected: **PROBE_REMOVED**.
   If it prints **STOP_OVERRIDE_STILL_ACTIVE**, leave the consumed flag in place
   and report the blocker. Never clear all browser/session storage.
6. Restore **Disable cache** to its previous setting, clear the DevTools display
   and close DevTools. Return only the sanitized three-field test result.

Chrome Local Overrides do not remove themselves. Automatic cleanup cannot be
guaranteed from page JavaScript. The explicit removal and original-hash check above
are required. The absolute two-hour expiry, manual-only trigger and consumed flag
limit the probe if the folder is accidentally left configured; none replaces
cleanup. No server-side file, endpoint, role or authentication setting changes.

## Offline reproducibility

```
/Users/iannganga/.nvm/versions/node/v22.22.0/bin/node --test frontend/acceptance/analyst-devtools/probe.test.mjs
```

`build.mjs` verifies the immutable manifest and original V5 reference bundle before
producing a new private artifact. It never retrieves a host baseline or executes a
browser. Source helpers/tests remain local reviewable code; the deployable V5
release, production dependency graph and deployed files remain unchanged.
