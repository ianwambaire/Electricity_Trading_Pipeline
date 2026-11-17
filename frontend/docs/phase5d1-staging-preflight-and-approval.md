# Phase 5D.1 — Integration preflight and infrastructure approval package

Date: 25 October 2026. Branch: `feature/react-frontend`; initial local revision `74afaff`. Final target: **React + FastAPI exclusively at https://powerflowenergy.dev**, retaining required ingestion, Prefect, SQLite/PostgreSQL, frozen inference, anomaly detection and MLflow state. Streamlit stays available until separately approved retirement. This report supersedes only the explicitly updated findings below, not earlier recovery/security requirements.

**Recommendation: ready to review a controlled, isolated staging plan; not approved for shared-host staging or production cutover.** Local data-filled integration is demonstrated. Installed Linux/Nginx behavior, representative resource peaks, recoverable production backups, renewal and production-client authentication remain gates. No AWS resource/configuration, account/group, production service/data, DNS/TLS setting or Git staging/history was changed. The only remote host actions were the exact additional read-only commands explicitly approved by the owner; SSH creates normal login audit records.

## 1. Evidence and boundaries

| Evidence | Actual result | Limit |
|---|---|---|
| Local app | Vite127.0.0.1:4174 → `/api` → FastAPI127.0.0.1:8011; staging host restrictions, docs disabled, real local snapshot | Development proxy, not installed Nginx/HTTPS or production Cognito |
| Local persisted data | 67,486 Silver observations; latest 12Sep2026 21:00UTC, price184.81EUR/MWh; 14,878 historical one-hour predictions; 674 persisted anomalies | Historical and degraded, never described as live |
| Missing real reports | next24, realized next24 errors, issuance history/provenance and two monitoring files absent locally | No reports generated, fabricated or withholding relaxed |
| Populated edge states | Separate synthetic backend child and simulated identity/profile, prominently labelled in browser | No real login/account/MFA assertion from these fixtures |
| AWS inventory/billing | Prior approved25Oct reads reused, approximately$95.25 estimated unspent credit | Open charges, taxes and future usage can change balance |
| New SSH | Exact four-command bundle completed, exit0; metadata below | No argv, environments, logs, secrets, unit contents or key material inspected; stderr existed and was not disclosed |

The private local snapshot uses an explicit data/artifact allowlist and SQLite online backup with `integrity_check`. Files are mode0600 under a0700 root outside the checkout; `.env`, secrets, logs and user files are excluded. Snapshot digests remained unchanged after the HTTP/browser checks. This is **not** a production backup/restore rehearsal. Source model binaries were copied for metadata availability, never fitted/executed by the API. The production API entry point and JWT dependencies were not altered.

`tests/preflight_server.py` is a local test entry only: main application retains JWT guards; a mounted `/__fixtures` child overrides Admin solely for synthetic/copy-based UI tests. Every non-GET/HEAD request is rejected405, provider JWKS fetching is disabled, MFA enrollment remains off. The browser fixture intercepts only simulated own-profile retrieval and labels its identity. It must never be deployed or exposed beyond loopback. Production build checks reject the fixture marker and development/test sources.

## 2. Approved host checks — new findings

Target: the sole running t3.small in us-east-1f whose public address matched powerflowenergy.dev; Amazon Linux2023, SSH `ec2-user`, existing approved key, strict pre-existing host-key verification, no host-key changes or agent. Existing root AWS CLI identity was used only for previously authorized read-only inventory; it is unsuitable for routine deployment. Future writes require a least-privilege operator identity and individually approved scope.

Exact commands executed:

```sh
systemctl show powerflow-api.service powerflow-prefect-worker.service powerflow-prefect-server.service powerflow-streamlit.service postgresql.service --property=Id,WorkingDirectory,FragmentPath,MainPID,User,Group,ActiveState,SubState,MemoryCurrent,MemoryPeak,MemorySwapCurrent,MemorySwapPeak,MemoryMax,TasksCurrent
ss -ltnp 'sport = :8000'
git -C /home/ec2-user/Electricity_Trading_Pipeline rev-parse HEAD
systemctl show certbot.timer certbot-renew.timer --property=Id,LoadState,ActiveState,SubState,UnitFileState,NextElapseUSecRealtime,LastTriggerUSec
```

| Unit | State | User/group | MainPID | MemoryCurrent bytes | Tasks | MemoryMax |
|---|---|---|---:|---:|---:|---|
| powerflow-api.service | active/running | ec2-user/ec2-user |1278418|8548352|2|infinity|
| powerflow-prefect-worker.service | active/running | ec2-user/ec2-user |1319862|336687104|7|infinity|
| powerflow-prefect-server.service | active/running | ec2-user/ec2-user |1942|220315648|10|infinity|
| powerflow-streamlit.service | active/running | ec2-user/ec2-user |1475479|206630912|11|infinity|
| postgresql.service | active/running | postgres/postgres |1899|239853568|14|infinity|

The four PowerFlow units report WorkingDirectory `/home/ec2-user/Electricity_Trading_Pipeline` and their matching `/etc/systemd/system/<unit>` fragments. PostgreSQL reports `/usr/lib/systemd/system/postgresql.service`, blank WorkingDirectory. These operational paths belong in this owner report, never a public API response.

`ss` confirms **uvicorn PID1278418 on127.0.0.1:8000**, matching powerflow-api.service. Checkout HEAD is **b165c8db5a208e8954058fac8cc415d7dfd53446**, locally identified as19Oct Cognito/role work. It differs from the candidate checkout. The source template at that revision uses `.venv-prod`, but the installed ExecStart, dirty state, loaded code and effective permissions were not inspected. Revision evidence alone does not identify the process's loaded implementation. Do not replace this unit/port or assume current security is deployed.

Requested MemoryPeak/MemorySwapCurrent/MemorySwapPeak fields were omitted: **no peak measurement was obtained**. Current counters are not additive unique physical RAM or capacity certification.

Renewal: `certbot.timer` not-found/inactive/dead; **certbot-renew.timer loaded, disabled, inactive/dead**, no next/last trigger returned. This resolves the previous timer ambiguity, not all possible cron/manual renewal arrangements. Public certificate previously validated through24Dec2026. Renewal ownership/configuration and successful dry-run remain blockers; no timer was enabled or renewal attempted.

## 3. Local integration and populated browser acceptance

The test server reads an immutable private copy of actual local inputs, not production. Vite's new server-only `POWERFLOW_DEV_API_PORT` defaults to8000 and accepts only integer1024–65535. Here8011 avoided other existing local8000 processes. It is not a VITE browser setting and does not change production `/api` contracts.

Read-only HTTP over the actual Vite proxy confirmed:

- 200: `/health`, `/pipeline/status`, `/operations/summary`, `/market/coverage`, `/market/history`, `/market/summary`, `/market/chart`, `/market/exploration`, `/anomalies/summary`, `/anomalies/events`, `/models/summary`, `/forecast/one-hour`.
- 404: absent `/forecast/next24`, `/forecast/realized-evaluation`; deployed-mode `/docs`. Missing inputs remain missing; no stale fallback.
- 422: invalid dates, `limit=2001` above the backend's2000-row ceiling. UI pages intentionally request1000rows.
- 401: own-profile without authentication, invalid Bearer token, and **all seven** Admin routes without authentication: `/admin/operations`, `/admin/forecast/provenance`, `/admin/models/linear-feature-influence`, `/admin/monitoring/forecast-vintages`, `/admin/monitoring/exogenous-readiness`, `/monitoring/forecast-vintages`, `/monitoring/exogenous-readiness`.
- Every checked API response retained `Cache-Control: no-store`; persisted row count/latest price matched CSV, and prediction count matched its report. No real tokens were retrieved or inspected.

Real JWT issuer/client/expiry/signature, Analyst403, Adminallowlists, own-account scoping, account failures and recovery authorization are covered by isolated backend regression tests. Session replacement, cancellation, timeout, rejected redirects, expiry gating, polling/retry and CSV error cleanup are covered by frontend regressions. These are not new live Cognito tests. Prior Google/native/TOTP/production Streamlit acceptance remains historical evidence; no new account recovery or MFA enrollment was authorized/performed here.

### Browser matrix

Each page was opened at **1280×900,768×900,390×900** against the actual snapshot and again against the labelled fixture surface:42 route/viewport checks. All page headings loaded, all present charts had nonzero dimensions/rendered SVG, and no document-wide horizontal overflow was observed. Wide tables retain their own scroll containers. Fixture identity/profile was used in **both** modes; real authenticated account UI was not tested.

| Page | Actual snapshot | Additional fixture coverage | Chart count actual / fixture |
|---|---|---|---:|
| Executive Overview | historical KPIs, 1579 sampled chart points from67486 source rows, price/load/wind+solar, degraded system, missing next24 |168synthetic source rows, synthetic execution |2 /2|
| Market Intelligence | generation means/weather and price/load/generation/share; missing nuclear remains missing |small168-row dataset |7 /7|
| Forecast Intelligence | latest historical context,14878historical one-hour records/chart last500, genuine frozen holdout metrics; next24/realized absent |24synthetic horizons,168historical records,24realized pairs, issue context, release separation, insufficient health coverage |1 /2|
| Anomaly Detection |674persisted events; chart and event tables |2synthetic events |1 /1|
| Model Insights |actual separate model identities/evaluation; Analyst coefficient restriction |Admin chart/table of copied genuine one-hour coefficients, not next24 influence |0 /1|
| Pipeline Operations |persisted summary, source/product/quality tables; Analyst restriction |bounded execution/incident/timing tables and monitoring, synthetic readiness NOT_READY |0 /0 (tables, no implemented chart)|
| My Profile |simulated profile only, no mutations |same; unavailable authenticator controls |0 /0|

Representative chart widths: Overview/Forecast908pxdesktop,674pxtablet,324pxmobile; height390/390/340. Model coefficient chart674pxtablet and324pxmobile with560/620px height. Market small cards441pxtodesktop,324pxtablet,322pxmobile. Axes/units and legend labels were inspected; forecasts distinguish elapsed/future predictions and historical actuals. Mobile narrow charts remain compact: exact UTC/value tables are the authoritative accessible alternative. This is visual checking, not a screen-reader/zoom certification or comprehensive browser performance profile.

Interactions actually verified:

1. Real market UTC dates1Aug–12Sep2026 returned1030records. Next page showed1001–1030; expanded exact-values table matched. Downloaded CSV contained **30rows**,11Sep16UTC through12Sep21UTC, first price248.49, snapshot`silver-ba5117637fdc2ad3`. No all-history export was implied by this page export.
2. Actual anomaly Next events showed101–200of674. Chart tooltip displayed19Apr2022 03UTC,200.61EUR/MWh.
3. Synthetic forecast tooltip displayed26Oct2026 02UTC,−4EUR/MWh, matching h+8 fixture. Legends distinguish future/elapsed and actual/predicted. Keyboard ArrowRight was exercised, but a change of selected tooltip point was not established; comprehensive chart keyboard accessibility remains an acceptance limitation.
4. Synthetic stale issue labelled **Stale**, withheld pipeline labelled **Withheld**, failed execution retained Withheld reference classification. Synthetic24realized pairs showedMAE/RMSE/bias1 and correctly insufficient health/horizon coverage. No confidence interval is implemented or invented.
5. Mobile navigation opened a labelled dialog; selecting Market Intelligence changed heading and closed it. Automated tests separately cover date-validation failures, collapse, retries, cancellation and error states.

An initially malformed **synthetic** evaluation fixture produced503; corrected field order and added a regression asserting24pairs/MAE1. All three forecast viewport checks were repeated after correction with two rendered charts and no alerts. Early rapid browser probes returned lazy-loading screens and were not counted as populated acceptance; final checks waited for data/chart elements. Real missing reports intentionally retain their error states.

## 4. Production Nginx proposal — not installed

Review files under `deploy/preflight/`:

- `nginx-http.conf`:5requests/second/IP,20requestburst,429status, privacy-minimized log format; size/performance settings are proposed and require a real browser waterfall test.
- `powerflowenergy.dev.conf`: final apex HTTPS static root`/var/www/powerflow/current`,wwwredirect, same-origin`/api/`→**127.0.0.1:8010/** (strip prefix exactly once), seven-route SPA history fallback, missing assets404, hashed-assets one-year immutable caching, indexno-store, ordinarySPA no-cache.
- `security-headers.conf`:short initialHSTSwithoutincludeSubDomains, no-referrer,nosniff,DENY,limitedPermissionsPolicy, compatible **Report-Only** CSP. Local fonts; explicit Cognito issuer/domain connect; Recharts inline styles need style unsafe-inline. No report collector receives callback query data. CSP is not yet enforced security protection.

API auth and errors pass through unchanged, no intercept/fallback to SPA.16KiBrequestlimit,3sconnect/30sread/10ssendtimeouts; no proxycache. `/api/ready` anddocs/openapi/redoc prefixes return404externally; readiness remains operator-loopback only. Hidden files/source/tests/data/artifacts are denied. Incoming spoofed forwarded-for/proto/Host are overwritten; Uvicorn trusts only loopback. This assumes Nginx is the direct public edge; adding CDN/ALB requires a separately reviewed trusted-proxy chain. Static assets can be public; actual API JWT/group authorization remains server-side.

Nginx access logging excludes IP,URI/query,Authorization,cookies,body/referrer; it records time/status/duration/bytes/generatedrequestID. Dedicated error log atcrit minimizes normal credential-bearing request diagnostics; severe errors can still contain request context. Restrict root-readable logs, bounded rotation/retention and never enable debug/request dumps. App logging uses server route templates and generatedIDs. Correlating Nginx and API IDs requires separate validation (API generates its own ID).

**Conflicts/gates:** current production apex routes to Streamlit; its websocket/8501 and`/oauth2callback` must be captured in a secure owner-sanitized diff and retained for rollback. The existing8000API has unknown consumers; new8010avoids replacement but availability and overlap capacity are unverified. Do not install competing duplicate server_name blocks. Proposed certificate paths must be verified against existing public certificate metadata; never read private keys. The existing ACME challenge method/webroot is unknown; preserve/merge it before any reload, not the redirect-only draft blindly. Generic static docs paths may SPA fallback, but `/api` privatepaths are blocked and FastAPI docs are disabled.

Validation status: static security guardrails pass; **no `nginx -t` was run**. Native Nginx is unavailable and Docker has no running engine; no software/daemon was installed or started. After separate isolated Linux approval, assemble includes/certificates/static release, run `nginx -t` (target configuration), test route refresh/assets/API401/403/404/422/503/bodylimit/rate429/timeouts/headers/cache/CSP and ACME renewal. Only then prepare the exact production diff and request reload approval. Preserve original configfiles/modes and test restoring them before cutover.

Nginx URI replacement follows the [official proxy documentation](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_pass). The repeated headers include avoids losing server headers in locations defining `add_header`; installed-version behavior still needs syntax/runtime checks.

## 5. Exact Cognito proposal — no changes applied

Prefer a **new public production client**`powerflow-react-production` in existing pool`us-east-1_NLoYFRvex`,us-east-1. Proposed complete create-request fields: `deploy/preflight/cognito-production-client.json`. Existing Reactdevclient`4t8s6a673a18qhbauqac8rhdcf` and Streamlitclient`5qa93km3lf2bbu3ffnrpea4r3g` remain unchanged.

| Setting | Proposed production value |
|---|---|
| Secret / grant |GenerateSecret=false; code only; library PKCE/S256, nonce and state; no implicit/password-grant substitution|
| Callback / logout |exact`https://powerflowenergy.dev/auth/callback` / `https://powerflowenergy.dev/`|
| Providers |COGNITO and Google; no mapping/user linking changes|
| Allowed scopes |openid,email,profile,aws.cognito.signin.user.admin|
| Requested on ordinary login |openid email profile; explicit fresh account-settings login adds self-service scope|
| ReadAttributes |email,email_verified,identities,name,preferred_username,sub|
| WriteAttributes |email,name,preferred_username (same reviewed SPA permissions)|
| ExplicitAuthFlows |ALLOW_REFRESH_TOKEN_AUTH,ALLOW_USER_AUTH,ALLOW_USER_SRP_AUTH|
| Access/ID TTL;refresh |60 minutes each; refresh 5 days; revocation enabled; AuthSessionValidity 3 minutes|
| Enumeration protection |PreventUserExistenceErrorsENABLED|
| Groups/role |unchanged verified`cognito:groups`; self-service scope grants no PowerFlow Admin role|
| Allowed browser/API origins |onlyapexsame-origin; API CORSempty; no wildcard; Cognito has no separate SPA “AllowedOrigins” field here|
| MFA |existing pool OPTIONAL/TOTP, enrollednativechallenge; Googleprovidersecurity; generalenrollmentoff inPowerFlow|

The JSON is a **proposal**, not a saved AWS readback or CLI command executed. New returnedclientID must be bound to the frontend build and dedicated candidate API's `POWERFLOW_API_COGNITO_CLIENT_IDS`; do not add it to the legacyAPIblindly. No secret or IDtoken is sent as API authorization; existing verifier checks access-tokenissuer/signature/token_use/expiration/clientbinding and configuredscopes. Refresh/revocation semantics remain documented: JWT verification alone does not instantly revoke already-issued accessJWTs; own-account operations validate with Cognito. TTL and logout behavior need live staging tests, not promises of immediate globalJWTinvalidity.

Prior audited Google mapping:email,email_verified,name,usernamefromsub. Recheck live mapping/schema/read-write compatibility immediately before any client creation; system-managedusername/email_verifiedare not ordinary profile writepermissions, do not expand allowlist to make a rejected request work. Google-mapped name staysprovider-managed; email write permission retained for federation does not authorize a PowerFlowemaileditform. Backend restricts updates toname/preferred_usernameforcurrentuser; verifiedemailchanges remain deferred. Follow [Cognito mapping guidance](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-specifying-attribute-mapping.html) and [explicit app-client permissions](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-client-apps.html); stop if current mapping differs or AWSrejectsattributes.

Isolated HTTPSstaging needs its **own** exact origin/callback/logout client and certificate, separately approved; proposed hostname`staging.powerflowenergy.dev`, initially3scopes for read-only identity/UI acceptance. Do not put staging callbacks into Streamlitclient or assume productioncertificatecoversstaging. A full self-service staging test additionally requires approval for self-servicescope and designated account actions. Neither new client authorizes live enrollment/recovery.

Rollback: before use, discard uninstalled candidatebuild/config; after approved use, restore compatible prior API/static/proxy/clientbinding and require fresh login. Retain existing clients through rollback. Deleting new clients or revoking sessions requires separate approval; never modify groups to make a test pass.

## 6. Dedicated Linux API design

Proposal: new `powerflow-react-api.service`, user/group `powerflow-api`, immutable releases `/opt/powerflow/releases/<reviewed-release>/`, symlink `/opt/powerflow/react-current`, isolated `.venv-api`, root-owned mode0600 `/etc/powerflow/react-api.env`. Systemd reads the environment before dropping privileges. Static releases live under `/var/www/powerflow/releases/<release>/` with a `current` symlink. The API reads `/srv/powerflow/published`, never the writer checkout or its secrets. The API environment excludes Streamlit, Prefect, model execution and administrative AWS credentials.

Publication remains a deployment integration gate. An approved publisher must produce a coherent immutable generation of reports, market observations, metadata and a consistent SQLite online backup, validate a manifest of watermarks/releases/digests, then atomically switch generations. Never copy an active SQLite/WAL set. Until this exists, staging uses a fixed, explicitly historical snapshot and cannot demonstrate continuous production updates. Do not introduce another writer or alter withholding rules.

Proposed permissions: release directories root:root0755, immutable code/venv; published root:powerflow-api0750 and files0640, writable only by the approved publisher; static dirs0755/files0644 without source/env/tests. The service account has no shell, sudo or home credentials. Keep existing pipeline/Streamlit identities unchanged. The template disables SDK metadata and denies both EC2 metadata addresses through systemd. Verify cgroup/BPF enforcement in Linux; stop for an approved alternative if unsupported. Cognito TLS/DNS egress remains necessary. Shared kernel, disk and instance failure risks remain.

The unit proposes loopback **8010**, one worker, concurrency32, keepalive5s, graceful shutdown20s/stop30s and failure restart5s. Initial hypotheses: MemoryHigh384MiB, MemoryMax512MiB, MemorySwapMax0, CPUQuota100%, TasksMax64. It restricts home/system/kernel/control-group access, devices and capabilities. These are not measured reservations or proof of capacity: isolated peaks must determine final caps. Follow [systemd resource-control semantics](https://www.freedesktop.org/software/systemd/man/258/systemd.resource-control.html) and validate the installed version.

Operator-only `/health` measures liveness; `/ready` returns200/503 for data readability/schema and **does not attest freshness**. Check operations and report watermarks separately. No pipeline is triggered by requests. Proposed logs are sanitized journald events with bounded retention, not request bodies/queries/tokens. Verify severe-error handling in staging using synthetic failures. Applying shared journal limits requires reviewing effects on other services.

Rollback changes only approved candidate unit/env/release/proxy pointers. Existing8000, Streamlit, databases and pipeline remain untouched. Port8010 availability, metadata denial, dedicated-user access and Linux sandboxing are unverified until staging.

## 7. Individually approvable infrastructure actions

**Every action requires separate explicit approval.** Before writes, bind the exact account, instance, volume, bucket, role, DNS and newly created resource IDs in a restricted change ticket. Verified logical targets are the sole production EC2 matching powerflowenergy.dev inus-east-1f, its20GiB unencrypted root, existing versioned private PowerFlowS3 backups and instance role, named units above and the specified Cognito pool/client IDs. Earlier reports omit infrastructure IDs; do not invent them or execute an ambiguous target selection.

| ID / target | Proposed action and prerequisites | Downtime / cost | Risk | Verification | Rollback |
|---|---|---|---|---|---|
|A1: operational SQLite, Prefect PostgreSQL, required MLflow state, reports/models, protected configuration and existing backup prefix|Consistent online SQLite backup; reviewed PostgreSQL dump and matching MLflow/artifact/config backup; manifests and off-host versions. Propose7daily/2weekly retention after sizing and acceptedRPO≤24h.|No planned stop for online backups; CPU/I/O peaks need testing. $3/month allowance until measured.|Cross-store inconsistency, credential-bearing backup, current role can delete versions.|Hashes, schema/integrity, complete generation, off-host version IDs and backup age.|Disable only new schedule; retain good backups. Deletion needs separate approval.|
|A2: disposable encrypted restore host/volume, private destination|Select immutable backup versions; restore SQLite to a new explicit path, PostgreSQL and MLflow in isolation. RequiresA1 and temporary-resource budget.|No production downtime;48h staging base~$1.34 plus storage/transfer.|Wrong destination, accidentally starting scheduler, leaking private config.|Actual restore, counts/digests/integrity, read-only API boot, recordedRPO/RTO and operator sign-off.|Leave production untouched; clean up isolated resources only with approval.|
|A3: existing production root EBS volume inus-east-1f|AfterA1/A2 and maintenance approval: consistent snapshot, encrypted copy, new encryptedgp3 root, preserve device/boot mapping. No in-place conversion.|Host stop affects all services; rehearse duration. Additional20GiB~$1.60/month while retained, plus snapshots/requests/KMS if applicable.|Boot/KMS/access failure, rollback data divergence.|Encrypted flag, boot/services/data/auth, recovery checks.|Approved stop and reattach retained original root; reconcile newer writes before any data rollback.|
|A4: apex/www certificate and certbot-renew.timer|Review sanitized installed ACME method/paths, then approve exact timer/dry-run/reload actions. Current timer disabled.|Usually no application stop; approved graceful reload. Certificate fee$0; monitoring allowance.|Broken challenge, rate limit, expiry.|Successful dry-run, active next timer, public chain/SAN/expiry, alert delivery.|Restore known-good renewal/proxy config; do not disable functioning renewal blindly.|
|A5: new powerflow-api identity/unit/8010|Isolated build/restore, free port, private env, permissions/metadata denial and capacity approved; old8000 consumer inventory.|No intended production stop in isolation; same-host overlap unapproved. No extra VM cost on same host.|Memory pressure, shared IAM/kernel, unknown old consumers.|Unit verification, denied writes/secrets/metadata, private listener, auth and resource measurements.|Stop candidate only, restore its env/symlink/proxy. Account deletion separately approved.|
|A6: published/release/static/env paths in section6|Approve coherent generation publication and read-only permissions; preserve writer paths.|No intended stop; copying adds temporary disk/I/O.|Partial data generation or historical snapshot mistaken for current.|Run as dedicated identity; verify hashes/watermarks, denied writes and next legitimate publication.|Restore retained publication pointer, never overwrite writer databases.|
|A7: candidate journal, dedicated Nginx logs, proposed PowerFlow/Production metrics and approved alert recipient|Privacy review; proposed14-day/100MiB local retention; CPU/memory/swap/disk/service/5xx/backup-age/TLS alerts. Review shared journal effects.|Normally no stop; $2/month allowance, exact agent/custom-metric pricing pending.|Sensitive diagnostics, alert costs/noise, agent RAM.|Synthetic safe alarm delivery, retention/rotation, no sensitive fields, measured cost.|Disable only newly approved collector/alarms; retain incident evidence.|
|A8: existing instance role and S3 backup prefix|Inventory consumers; separate publisher/restore roles; review removal of DeleteObject/DeleteObjectVersion on backups and bounded lifecycle. No ObjectLock change implied.|No planned downtime; IAM$0, retained versions billable.|Breaking sync/restore or making retention irreversible.|Policy simulation and approved isolated-prefix permission tests; restore identity works.|Restore reviewed prior policy version; no unreviewed privilege expansion.|
|A9: existing t3.small and required services|Approve exact bounded passive sampler during an already scheduled run; no production load. Follow with isolated cold/warm/rebuild/backup/inference replay.|No intended production downtime; passive sampling no new resource fee.|Observation misses peaks; caps can still OOM.|≥25%RAM/disk reserve, no sustained swap/OOM/restarts, agreed latency/error budgets.|Stop isolated workload, not production pipeline. Resize/Streamlit stop separately approved.|
|A10: proposed temporary encrypted t3.small20GiB staging, hostname staging.powerflowenergy.dev and separate client|A1/A2, exact resource IDs/SG/DNS/TLS/client approval; snapshot only, no scheduler/admin credentials;48h goal/14-day review limit.|No production downtime.14-day base~$9.41+$2 variable allowance; cleanup approval required.|Shared user pool is not account isolation; overrun billing, public market contract.|All section9 checks, resource/cost review, separately approved live identities.|Remove exposure/restore isolated release; delete VM/disk/IP/DNS/client only with explicit approval.|
|A11: production apex Nginx and new production client|All gates, exact installed diff, artifact/client IDs, maintenance and rollback operator. Preserve existing clients.|Brief graceful switch after rehearsal; no zero-downtime promise.|Callback loops, wrong client/role, cache/CSP, old consumers.|Seven routes, fresh identities, all seven403s, Admin allowlists, data/operations checks.|Restore exact saved routing/release/config; fresh sign-in, no database restore just for web rollback.|
|A12: powerflow-streamlit.service and Streamlit-only code/deps/config/client|Owner acceptance after proposed≥7days normal React operation, rollback retention and shared dependency review. Stop/disable first; later cleanup approval.|Only old UI stopped after approval; shared environments preserved.|Deleting shared pipeline dependencies or rollback.|Full tests/imports/model digests/pipeline/backups; review8501 and client retirement.|Restore retained Streamlit release/unit/config/client within rollback window. Destruction separately approved.|

Tickets need exact IDs, least-privilege operator, cost cap, maintenance/observation window, rollback operator and stop conditions. Root is not recommended for routine operations. Do not create a new identity or policy without its own review. Infrastructure restoration and live user-account recovery are separate scopes; the latter remains excluded.

## 8. Capacity and two-month budget

The25Oct20:25Nairobi snapshot showed1909.74MiB RAM,1026.27MiB available,817.42MiB swap used, no swap I/O across9fresh intervals and11.93GiB free disk. With25%physical-RAM reserve, only~549MiB incremental idle headroom remains. New unit counters confirm concurrent API/Streamlit/Prefect/PostgreSQL, but no peak fields were returned. **No production load or forecast execution occurred.**

A prebuilt React bundle and one API worker avoid a Node server and duplicated model runtimes. Preserve MLflow state/research without assuming another always-running public MLflow server. Prior local measurements included eight function calls/four threads in~1.066s and a~1.69MB one-hour report; these and current HTTP checks are not Linux peak-capacity evidence. Cold index replacement, JSON serialization, backups, inference and PostgreSQL can overlap. A512MiB limit does not prove the rest of the host fits.

Smallest additional validation: approve an exact bounded passive memory/swap/disk sampler during normal scheduled work, plus isolated Linux replay. No further SSH was run. Same-host staging remains blocked until peaks, recovery, isolation and renewal are verified.

| Budget component | USD/month | Basis / limitation |
|---|---:|---|
|t3.small730h|15.184|Previously verified0.0208/h; surplus CPU credits can add cost|
|One publicIPv4|3.650|0.005/h; retained addresses may continue billing|
|20GiBgp3|1.600|0.08/GiB-month|
|Backup storage/versions/requests|3.000|Allowance, not measured retention cap|
|Transfer/variable usage|2.000|Allowance|
|Monitoring/logging|2.000|Allowance; exact agent/metric plan pending|
|Contingency|4.000|Must cover unpriced usage/migration overlap or trigger revision|
|**Single-host planning total**|**31.434**|Within30–35target before taxes/overruns|

Two months62.868 +14-day temporary stage9.405 +2variable allowance = **74.273**, average37.14/month. This exceeds the preferred monthly range during staging but stays below47.50maximum average. Estimated95.25credits leave~20.98headroom. A48hstage costs~1.34base instead; permanent dual hosts are not selected. A t3.medium with the same allowances is~46.62/month and leaves little contingency.

Credit evidence is from previously approved25Oct reads, not a new billing query: finalized112.12 less estimated open charges gives95.25; expiry19Sep2027; relevant EC2/VPC/S3/CloudWatch/Cognito/KMS/Backup/CostExplorer usage was eligible under the inspected credit description. October1–24gross usage16.8031before credits. Taxes, support, ineligible charges, application timing and overruns can require cash payment. Credits are not a guaranteed spending cap.

Let's Encrypt certificate fee is$0; renewal work/monitoring still matters. Domain renewal was not newly priced; review if due. Root encryption temporarily duplicates volumes/snapshots: measure retained bytes/duration and revise budget if allowances are insufficient. Stopped VMs, disks, IPv4 and noncurrent S3 versions can still bill. Cleanup and retention must be explicitly approved; measure gross charges, not only the credit-adjusted invoice.

## 9. Controlled staging runbook — proposals only

1. **Lock approval and targets.** Prefer isolated staging with48hgoal/14-day review over unproven overlap. Record exact account/region/resource IDs, owner, cost cap, cleanup, hostname/client/SG/TLS. Same-host staging requiresA9 and separate production-host approval. Never start another scheduler, pipeline writer or database stack merely for API testing.
2. **Back up and actually restore.** CompleteA1/A2. Approved operational SQLite commands are `python scripts/backup_operational_state.py --database <verified-db> --output-root <approved-private-backup-root>`, `python scripts/validate_operational_backup.py <selected-backup-dir>`, then `python scripts/restore_operational_state.py <selected-backup-dir> --destination <new-isolated-db>`. Resolve placeholders, do not paste them into a shell, and never use`--force` here. PostgreSQL/MLflow/configuration require their own reviewed consistent recovery procedure. Never publish private configuration with market data.
3. **Prepare artifacts locally/CI.** Owner chooses a clean reviewed release; this agent performs no Git writes. Clean Linux build with approved Python3.14 and compatible Node/npm, exact locks and hashes: `npm ci`, tests/lint/build/check-build; API install into`.venv-api` with `python -m pip install --require-hashes -r requirements/api.lock`, test environment separately viaapi-test.lock. Do not copy a Mac venv or compile/install an unreviewed interpreter on production. Build with approved staging public settings, never secrets. No test entries, source maps or `.env` in static artifacts.
4. **Install only on approved isolated Linux.** Dedicated identity, immutable releases, private environment and approved snapshot publication. No administrative credentials/ingestion secrets. Check port8010 is free and permissions/metadata denial actually work. Use stagingAPIENV/allowed host and separate staging client, not the production example unchanged.
5. **Assemble Nginx/TLS.** Adapt the final-domain proposal to exact approved staging hostname, fixed proxyHost, paths and trusted certificate. Preserve ACME method; include http zones/log format once. Run `nginx -t` against assembled config and `systemd-analyze verify /etc/systemd/system/powerflow-react-api.service`. Unsupported security directives are blockers. No production reload/config overwrite.
6. **Start approved candidate only.** On isolated host: approved `systemctl daemon-reload` and `systemctl start powerflow-react-api.service`; check `curl --fail http://127.0.0.1:8010/health` and `/ready`. A503readiness stops release;200does not establish freshness. Public`/api/ready`must404. Validate before starting/reloading isolated Nginx. None of these service commands was executed here.
7. **Routing and confidentiality.** Verify trusted HTTPS, redirects, seven direct routes/history refresh/callback, missing asset404, APIJSON/noSPA,401/403/404/422/503,16KiBbody413, rate429/timeouts, API-no-store/index-no-store/immutableassets, report-onlyCSP, private readiness/docs and denied source/data/env. Test normalized URL/host variants and spoofed forwarded headers. No query/body/credential logs.
8. **Live identities require separate test approval.** User enters credentials/TOTP directly in Cognito. Fresh GoogleAdmin and nativeAnalyst code+S256PKCE/state/nonce/client/redirect, already-enrolled dedicated TOTP challenge only. Verify server role, all seven Analyst403s, Admin permitted fields, expiry/refresh/session replacement/callback errors/logout/back-button behavior. No token printing/storage. Editing/password/recovery/enrollment require specific separate authorization; a read-only staging ticket does not authorize them.
9. **Data and page parity.** Compare persisted counts/watermarks/values/digests/model periods with the approved generation. Seven populated routes, CSV scope/UTC, filters/pagination/tooltips/legends/keyboard/touch/table overflow at desktop/tablet/mobile and zoom. Real next24success requires legitimate persisted evidence and unchanged withholding; otherwise record the blocker. No invented confidence intervals or synthetic production values. Verify current publication after a normal scheduled run without triggering one.
10. **Measure in isolation.** Cold/warm/rebuild concurrent HTTP, serialization, backup and representative frozen inference on copied inputs, with no production write credentials. Record latency,5xx, peaks, swap and disk. Propose p95<2sordinary bounded reads, zero unexplained5xx and≥25%memory/diskreserve; agree a separate large-report budget first. Inference stays outside API runtime. Isolated replay does not replace passive normal-schedule production observations.
11. **Abort safely.** Stop acceptance on wrong role, callback/MFA/session failure, unexpected write, secret exposure, OOM/restart/swap thrashing, data mismatch, readiness/TLS/backup failure. Remove only approved candidate exposure and restore its known-good release. No privileged workaround, group change, relaxed withholding or stale database overwrite.
12. **Record and clean up with approval.** Capture actual resource/artifact/client IDs, costs, RPO/RTO and limitations. Request production cutover only after gates pass. At deadline, obtain named-resource cleanup approval covering VM/disks/IP/DNS/client and retained snapshots; no automatic deletion.

## 10. Production cutover, rollback and Streamlit retirement

1. Pass recovery, encryption, renewal, isolation, peak-capacity and staging gates. Resolve old8000consumers and exact installed Nginx/ACME diff. Root-volume migration and web cutover should not share an untested maintenance window.
2. Owner approves exact resources/diff/release/client IDs, cost, maintenance and rollback operator, with proposed15-minute decision window after switch. Securely retain old unit/env/proxy/client config and hashed assets. Pipeline, PostgreSQL/SQLite and required MLflow stay intact with one writer. If overlap cannot fit, seek explicit maintenance/Streamlit-stop approval; it is not implicit.
3. Create approved new production client, read back exact settings/mapping compatibility and bind returnedID to frontend and dedicated candidateAPI. Existing clients/groups/pool remain unchanged. General MFA enrollment remainsfalse. Verify artifacts, private8010readiness and measured capacity before changing routing.
4. Apply only separately approved exact apexNginxdiff, preserving ACME and rollback. `nginx -t`, then approved graceful `systemctl reload nginx`. Domain/IP can remain; no intrinsic DNS change. Prebuilt React serves apex and same-origin API proxies to8010; no development server. Old8000retirement requires its own consumer review.
5. Verify fresh approved GoogleAdmin/nativeAnalyst/enrolledTOTP, production callback/session/logout, all seven Analyst403s/Admin allowlists, seven pages/data/CSV and legitimate publication. Monitor errors/latency/roles, memory/swap/disk, scheduled pipeline, backup/TLS and gross billing. No pipeline-run/train actions in acceptance.
6. **Rollback immediately** on wrong privilege, loops/MFA/session failure, unexpected writes, missing required parity, value/digest mismatch, pipeline disruption/OOM/swap thrashing, TLS/readiness failure. Restore saved compatible Nginx/static/API/env pointers, syntax-test and approved reload. Existing Streamlit client/entry returns; restart its service only if an earlier stop was authorized. Fresh sign-in, no cross-framework session transfer. Web rollback does not overwrite databases with stale backups; disaster recovery is a separate decision.
7. Proposed≥7days normal scheduled operation/traffic/backup/renewal observation, owner acceptance and agreed retention. Preserve rollback release/config/client/assets throughout. No automatic destructive cleanup.
8. **Separate approval** to stop/disable `powerflow-streamlit.service`, then later remove Streamlit-only code/dependencies/config/client/secrets. Audit call sites first. Preserve `src/shared`, API/auth, ingestion/validation, Prefect, storage/recovery, feature engineering, frozen models, SQLite/PostgreSQL and necessary MLflow history. Do not delete `.venv-prod` while pipeline uses it. Retire8501and old8000only after consumer checks. Re-run full regression/import/model-digest/recovery checks; owner handles Git.

## 11. Gates and Phase 5D.2 acceptance

| Gate class | Required evidence | Current status / blocker | Responsible next action | Separate approval | Verification |
|---|---|---|---|---|---|
|Satisfied: local safety|No production/auth/model contract changes; fixtures excluded|Regressions/build guardrails pass|Owner reviews diff/artifacts|No|Fullpytest; frontend test/lint/build/check-build|
|Satisfied: actual integration|ProxyHTTP and persisted-value matching|Passed; missing reports explicitly missing|Keep availability honest|No|check_preflight_http.py|
|Satisfied: populated layout|Seven pages×3sizes, real/fixture provenance|42checks; keyboard point change unproven|Owner visual review|No|Section3 matrix/interactions|
|Local/data: legitimate reports|Real next24/realized/monitoring evidence|Absent locally; fixtures do not close gate|Data owner supplies legitimate approved generation|If production retrieval/generation needed|Counts, watermarks, digests, withholding|
|Linux: syntax/runtime|Locked Linux install, unit/Nginx verification|No local Nginx/engine; no Linux staging|Operator A10|Yes|nginx-t, unit verify, pip/import/runtime|
|AWS: recovery/encryption|Actual restore and encrypted-root remediation|A1/A2 passed; A3 off-host/full-store recovery pending; root unencrypted|Operator A1–A3|Each separately|Manifest/integrity/RPO/RTO/encryption readback|
|AWS: renewal|Working ACME/timer/expiry alerts|Renewal timer disabled/inactive|Operator A4|Yes|Dry-run/timer/public cert|
|AWS: isolation/publication|Dedicated identity, read-only coherent publication|CurrentAPIec2-user/infinite cap; publisher pending|Operator A5/A6/A8|Yes|Permissions/metadata denial/binding/hashes|
|AWS: peak capacity|Normal-schedule observation plus isolated replay|Idle only, no peak counters|Owner approves exact sampler; operator observesA9|Yes|Memory/swap/disk/latency thresholds|
|AWS: staging budget/client|Exact target IDs/origin/cost/lifetime|No provisioning approved by report|Owner A10decision|Yes|Inventory, billing, client readback|
|Live staging: identity|Fresh Google/native/TOTP, seven403s, Admin allowlists, logout|Not repeated here; previous acceptance historical|Owner interactive/approved operator|Yes|Server roles/statuses, no secret capture|
|Live staging: data/operations|Real required data, proxy/browser/resource/rollback tests|Only local partial evidence|Operator section9|Yes|Recorded checklist and metrics|
|Production cutover|All prior gates, exact diff and rehearsed rollback|Not ready|Owner A11|Yes|Section10 decision window/checks|
|Decommission|Stable replacement, retained rollback, dependency audit|Not authorized|Owner A12|Yes|Stop/cleanup review and regressions|

Phase5D.2 must record exact approvals/resources/releases/client IDs/costs; real backup restoration; clean Linux import/dependency/unit/Nginx tests; no secrets/fixtures shipped; trusted stagingTLS and renewal; cache/CSP/private readiness; legitimate data and seven populated pages; fresh identities/server roles/seven403s/Admin allowlists/expiry/logout; measured resource headroom; coherent publication/single writer; and rollback rehearsal. Deliberately absent reports or public API contract decisions need explicit owner acceptance. General-user MFA enrollment and lost-device recovery remain **not production-certified** by these tests.


## 12. Validation results and reproduction

| Command / scope | Result |
|---|---|
|`venv/bin/python -m pytest -q`|**654 passed**,33.18s, including model, pipeline, Streamlit, auth and new preflight tests|
|Minimal API suite below|**210 passed,3 deselected**,5.65s; one existing AnyIO deprecation warning|
|`venv/bin/python -m pytest tests/test_staging_preflight.py -q`|**3 passed**; snapshot safety, retained JWT boundaries/fixtures, static proposal guardrails|
|`npm test` fromfrontend|**81 passed**,0 failed on complete rerun|
|`npm run lint`|Passed|
|`npm run build`|Passed, including TypeScript project build|
|`node scripts/check-build.mjs`|Passed; entry376359bytes/114072gzip, total886058JSbytes/30chunks,0maps/testsources/fixturemarkers|
|`npm audit --json`|0known vulnerabilities after approved registry access|
|`venv/bin/python -m pip check` and minimal API environment equivalent|No broken requirements|
|`venv/bin/python scripts/check_production_imports.py`|Passed; frozen release/runtime imports, not pipeline execution|
|`/tmp/powerflow-api-5b1-clean/bin/python scripts/check_api_runtime.py`|Passed; excludes Streamlit/MLflow/Prefect/sklearn/joblib/boto3; lifecycle/publichealth/protected401/missing503and404|
|LoopbackHTTPpreflight|Passed proxy/status/count/value/digest checks; no real Cognito|
|Browser|42route/viewport checks with explicit real/fixture boundary; interaction evidence section3|
|`git diff --check`|Passed; no staging/history writes|
|Nginx/systemd/Linux deployment validation|**Pending**, no nativeNginx/runningDocker or approved Linux deployment; static guardrails are not syntax validation|

Initial failures are retained honestly: the first concurrent frontend run stopped in the MFA test file after 77 passes with a file-level failure and no diagnostic cause; a full separate rerun passed all 81 tests. No authentication change was made to mask it. An over-broad minimal-environment selection had13 missing-dependency failures for joblib/Streamlit; those cases pass in the full 654-test suite. The correct existing API-only selection below excludes Streamlit parity fixtures and deselects3 pre-existing model-runtime instrumentation tests. One initial selection used a nonexistent filename and collected no tests. No dependencies or global skips were added. A synthetic evaluation-field ordering defect was fixed and regressed. An HTTP probe initially used1001 as the assumed row ceiling; source inspection established2000 and  the corrected2001 invalid-input probe passed. npm advisory lookup initially lacked DNS access; the permitted registry retry succeeded. Pip emits a local cache-permission warning; no sudo/cache changes. These are local validation issues, not production failures.

From repository root, the exact final minimal selection:

```sh
/tmp/powerflow-api-5b1-clean/bin/python -m pytest -q -m 'not model_runtime' tests/test_api.py tests/test_api_security.py tests/test_account_management.py tests/test_mfa.py tests/test_backend_hardening.py tests/test_public_market_api.py tests/test_api_deployment.py tests/test_phase5_restoration.py tests/test_streamlit_decoupling.py tests/test_staging_preflight.py
```

This reuses the existing private API-only environment; it is not a portable installed-path guarantee. A clean approved Linux environment must reproduce the locks. Other validation commands:

```sh
venv/bin/python -m pytest -q
venv/bin/python -m pip check
venv/bin/python scripts/check_production_imports.py
cd frontend
npm test
npm run lint
npm run build
node scripts/check-build.mjs
npm audit --json
```

Local actual-data browser reproduction (separate terminals, no real authentication):

```sh
# Repository root. Use a NEW private destination outside the source tree.
venv/bin/python scripts/prepare_preflight_data.py --source . --destination /tmp/powerflow-5d1-actual
POWERFLOW_PREFLIGHT_ACTUAL_ROOT=/tmp/powerflow-5d1-actual POWERFLOW_PREFLIGHT_FIXTURE_ROOT=/tmp/powerflow-5d1-fixtures PYTHONPATH=src:tests /tmp/powerflow-api-5b1-clean/bin/python -m uvicorn preflight_server:factory --factory --host 127.0.0.1 --port 8011 --workers 1 --no-access-log
```

```sh
POWERFLOW_DEV_API_PORT=8011 VITE_COGNITO_CLIENT_ID= npm --prefix frontend run dev -- --host 127.0.0.1 --port 4174 --strictPort
venv/bin/python scripts/check_preflight_http.py --snapshot /tmp/powerflow-5d1-actual
```

The snapshot command intentionally refuses an existing destination; use a new suffix and update both environment paths for another run. Do not delete/reuse someone else's directory. Local test URL: `http://127.0.0.1:4174/tests/browser/preflight.html?mode=actual&route=%2Fanalytics`. Seven route parameters are `/`,`/analytics`,`/forecasting`,`/anomalies`,`/models`,`/pipeline`,`/profile` (URL-encode them). `mode=fixtures&role=Admin` selects the labelled synthetic child; `stale`,`withheld`,`failed` cover reference states. Identity/profile is **always simulated**. Blank client override prevents a real OIDC manager. Never expose this development server or test backend publicly.

The HTTP script specifically expects this repository's current missing-report fixture and default local ports; it is not a generic production health check or safe substitute for live auth testing. Browser download verification created `~/Downloads/powerflow_displayed_market_page.csv` (30real historical rows); it was read back, not uploaded anywhere. No credential/account/MFA material was captured.

Temporary logs/summaries are under`/tmp/pf5d1-*`, not committed evidence. Relevant results: `backend-final.log`, `minimal-final.log`, `frontend-retry.log`, `lint.log`, `build.log`, `build-check.json`, `audit.json`, `http-result.json`, `approved-host-output.txt` and`host-meta.json`. Do not publish host operational metadata in a public API. Local test servers are stopped after validation; existing port8000processes are not touched.

## 13. Changed files and approval recommendation

Production-source changes are limited to the server-only dev proxy port and build-artifact exclusion guard. No production backend/auth/model/pipeline/Streamlit code or dependency lock was changed.

- Modified: `frontend/vite.config.ts`, `frontend/scripts/check-build.mjs`.
- Added local test tools: `scripts/prepare_preflight_data.py`, `scripts/check_preflight_http.py`, `tests/preflight_server.py`, `tests/test_staging_preflight.py`, `frontend/tests/browser/preflight.html`, `frontend/tests/browser/preflight.tsx`.
- Added proposals only: `deploy/preflight/README.md`, `nginx-http.conf`, `security-headers.conf`, `powerflowenergy.dev.conf`, `powerflow-react-api.service`, `api.env.example`, `cognito-production-client.json`.
- Added: this report.

Next review should select **A1/A2 backup and isolated restoration**, **A4 renewal review/remediation**, **A9 bounded passive capacity observation**, then a cost-capped **A10 isolated staging** ticket with exact resource/client/origin settings. These are requests for future approval, not execution here. Do not approve shared-host overlap from idle counters, deploy the draft Nginx configuration without installed syntax/ACME checks, or call the missing-data/identity gates complete on the strength of fixtures. Production cutover and final Streamlit retirement remain separate decisions.
