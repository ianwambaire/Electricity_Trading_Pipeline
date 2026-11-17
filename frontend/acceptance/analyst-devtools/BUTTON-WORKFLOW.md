# Analyst check without Console pasting

This uses Chrome's supported file-based Local Overrides and a temporary local
button. Do not type `allow pasting`, disable Self-XSS protection, change Chrome
flags, install extensions or modify authentication. No live test was executed
during preparation. If Chrome blocks this workflow with a security warning, stop.

The probe uses the exact V5 module-scoped client, its original session assertion,
the same bounded response check and the same consumed-marker protection as the
previously tested probe. It makes no request until you click the local button.
No request headers, credentials, cookies, token values, raw bodies or authentication
storage are inspected, printed or saved by the probe. The only storage access is
the fixed non-secret one-shot flag. The output is three sanitized fields.

## Verify the original file (no Console)

1. Leave the existing staging tab signed in as **Analyst**, on
   `https://staging.powerflowenergy.dev/pipeline`. Keep Local Overrides disabled.
2. In DevTools **Network**, with Preserve log off, reload that page once. Confirm
   the app loads **index-B_Ifb4TY.js** as its entry script. Do not open request
   Headers, copy requests, export HARs or save authenticated responses.
   If the entry script differs, stop; this artifact targets V5 only.
3. In a separate Chrome tab open this public JavaScript URL:
   `https://staging.powerflowenergy.dev/assets/index-B_Ifb4TY.js`.
   Save it with **Command–S**. In the save dialog use **Shift–Command–G** to select:

   ```
   /Users/iannganga/Desktop/electricity-trading-pipeline/data/backups/private-staging-browser-acceptance/devtools-analyst-button-v5-CM1yCQ/public-original
   ```

   Save with the exact filename **index-B_Ifb4TY.js**. Save only this public asset,
   not an API response, a HAR or an authenticated page. Close the public-asset tab.
4. Open macOS Terminal and run this local, file-only hash verifier:

   ```sh
   /Users/iannganga/.nvm/versions/node/v22.22.0/bin/node /Users/iannganga/Desktop/electricity-trading-pipeline/frontend/acceptance/analyst-devtools/verify-saved.mjs /Users/iannganga/Desktop/electricity-trading-pipeline/data/backups/private-staging-browser-acceptance/devtools-analyst-button-v5-CM1yCQ/public-original/index-B_Ifb4TY.js
   ```

   Proceed only if it prints **V5_BUNDLE_MATCH**. It performs no network request
   and cannot invoke the endpoint test. Any mismatch is a stop.

## Apply the local file and click once

1. In the original staging tab open **Sources → Overrides → Select folder for
   overrides**. Use Shift–Command–G in the folder chooser and select exactly:

   ```
   /Users/iannganga/Desktop/electricity-trading-pipeline/data/backups/private-staging-browser-acceptance/devtools-analyst-button-v5-CM1yCQ/overrides
   ```

   Allow DevTools access to only this prepared folder and enable Local Overrides.
   This is normal scoped folder access, not disabling a security protection. Do
   not grant access to your project root, Chrome profile or Downloads folder.
2. In Network enable **Disable cache** while DevTools is open, and reload the
   original Pipeline Operations page once. Confirm the exact entry script has the
   purple Local Overrides indicator. Confirm the application still shows Analyst.
3. At the top of the page find **Local-only Analyst authorization test**. The local
   button is **Run Analyst authorization check once**. If the panel is absent,
   expired, the role is wrong, or the override indicator is missing, stop.
4. Click the button **once**. It disables immediately. Do not duplicate the tab,
   reload to try again or change accounts. The only probe request is the existing
   client's `GET /api/admin/operations/current`.
5. Read the JSON directly below the button. Expected:

   ```json
   {"httpStatus":403,"adminDataDisclosed":false,"result":"PASS"}
   ```

   Share only those three fields. A null, unexpected status or FAIL is not a pass;
   do not inspect raw response bodies or retry. No Console code is involved.

## Remove after either result

1. Uncheck **Enable Local Overrides**. Remove this folder from the Sources
   workspace/Overrides listing if Chrome offers **Remove from workspace**.
2. In Finder delete only **devtools-analyst-button-v5-CM1yCQ** and its contents.
   Leave all parent evidence directories and Chrome profile files alone.
3. Restore Disable cache to its prior setting. Reload staging and confirm the
   local test panel and purple override indicator are both gone. If either
   remains, stop and report it; do not make another endpoint request.
4. Close the staging test tab. This clears its tab-scoped non-secret consumed
   marker without opening or clearing authentication storage. Do not restore or
   duplicate that test tab. Clear the DevTools display and close DevTools; do not
   save/export its network log. You may open staging normally afterward; another
   manual sign-in may be needed because the old tab was closed.

Chrome Local Overrides persist until manually removed: automatic unregistration
cannot be promised. These cleanup steps are required. The button never runs
automatically, is one-shot, and expires at **22:16:11 Nairobi on November 7, 2026**
(19:16:11 UTC). Expiry or disabled state is not permission to reset or rerun it.

## Bindings and local validation

- V5 original: 383151 bytes, SHA-256
  `e5c1053921f36b834a80bd7b73b3fb61f9a77c76de02922a1af877243c736e71`.
- Button override SHA-256:
  `6212c37fcd067b64f7737e8d8c2db1ff6aa6bdec37c02ad115e05485dfbcb982`.
- Existing immutable V5 manifest remains unchanged.
- 31 offline tests passed, covering the core guards, no automatic request,
  duplicate-click protection, expiry, exact bundle assembly, saved-file hashing,
  symlink rejection and sanitized display. No browser or staging request was used.
- Bounded response inspection: 4096 bytes, three-second read timeout. Only the
  exact public permission error with no extra fields establishes no disclosure.
  Unknown disclosure is null and FAIL. No sensitive payload is rendered.
