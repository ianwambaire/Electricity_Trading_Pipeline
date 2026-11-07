# Local operational-current routing proposal

No deployment, reload, configuration write or execution authorization is implied.
The v4 rollback completed; its immutable API/static/helper/store artifacts and
transaction evidence remain retained, while operational delivery is disabled.
Do not retry v4 apply: its initial absence gates correctly reject retained paths.

The archived approved staging Nginx allowlist excludes exactly the three required
routes: /api/operations/current, /api/pipeline/current and
/api/admin/operations/current. This is a confirmed local integration omission.
The authorized inspection on2026-11-07 verified the active config exactly matches
this archived source. All three routes return404 text/html,146bytes through Nginx,
reproducing HTTP_BOUND's content-type rejection. The original failing endpoint was
not captured, so its precise historical response remains unknown.

routing.py is a pure patch operation. It verifies the original approved release
manifest/configuration hash, accepts only the expected closed route inventory,
requires the exact staging server/API scope, and changes one allowlist line.
All unrelated supplied configuration bytes remain unchanged. Ambiguous, previously
patched or drifted inventories are rejected. No filesystem or remote writes occur
in the module. The generated config and ROUTING-PROPOSAL.json are local review
artifacts, not an instruction to replace an installed config from an old archive.

Authorization forwarding, backend Admin enforcement, TLS, no-store headers,
timeouts, body limits, rate limits, proxy target and internal-route denials are
unchanged. Offline tests reproduce the original policy denial, exercise the three
additions, preserve existing routes/reject extra paths and use the real FastAPI
application with synthetic empty roots to check MISSING/no-store and anonymous
Admin rejection. These are not live Nginx/browser acceptance claims.

No local nginx binary is available; nginx syntax and actual installed configuration
have not been validated. The active-config/routed-response evidence is now available and v5 binds it.
A future guarded apply must preserve unrelated settings, include independent
backups and nginx -t,
and authorize any required Nginx reload explicitly. Reconcile the exact retained v4
artifacts with a new transaction; never bypass collision/drift guards. Verify all
three new routes through Nginx before enabling operational delivery last. Then use
a genuine natural run and owner-authenticated React acceptance, never a manual run.
