# Local web release preparation (no deployment)

`scripts/prepare_web_release.py` validates an already built `frontend/dist`, public
release settings, allowlisted API/shared Python sources and existing hashed API
lock. It defaults to a dry run. It never invokes Git, npm/pip, AWS, SSH, Nginx,
systemd, network calls or application/model/database code. The existing8010candidate
unit/proxy remain proposals; existing8000and Streamlit services are untouched.

1. Copy `release-settings.example.json` to a private local settings file and replace
   the placeholder client ID with a separately approved public client. The example
   deliberately fails validation as written. No secrets, passwords, tokens or
   arbitrary extra settings keys are accepted. The staging hostname is a proposal,
   not a provisioned/approved origin.
2. Complete existing application tests/lint/release build (`npm run build:release -- --origin https://APPROVED_HOST`) and `node scripts/check-build.mjs`
   from `frontend/` first. This tool does not build or certify source behavior.
3. From repository root, with actual reviewed settings/release names:

```sh
venv/bin/python -B scripts/prepare_web_release.py --settings /absolute/private/public-release-settings.json --release-id REVIEWED_RELEASE_ID
```

The dry run writes nothing. For explicitly requested **local-only** packaging, add
`--write /absolute/private-parent/NEW_RELEASE_DIRECTORY`. The directory must not
exist, must be outside the repository, and its parent must be owned by the operator
and not group/other-writable. Output root is0700and files0600. The local free-space
guard reserves twice the package size plus64MiB. Partial output is preserved on
failure; there is no delete, overwrite, force or symlink-switch option.

```sh
venv/bin/python -B scripts/prepare_web_release.py --verify /absolute/private-parent/NEW_RELEASE_DIRECTORY
```

Verification is read-only, rejects extra/missing files, symlinks and digest/size
changes. SHA256 manifest integrity is not cryptographic signing or provenance;
record its digest independently during the release review. The static guard checks
known fixture markers, development/private filenames, maps, obvious private keys
and AWS access-key patterns; it is **not a comprehensive secret scanner**. Embedded
OIDC library configuration strings are not proof of a secret leak. API source and
configuration proposals are copied from explicitly allowlisted paths, never `.env`,
data, trained models, virtualenvs, tests or deployment credentials.

A release-eligible `build-config.json` must match schemaVersion1, same-origin `/api`, approved origin and SHA256 of the ordered public Cognito configuration (issuer/domain/client/callback/logout/API). Generic local builds are refused. The static JavaScript must contain the expected public client ID, issuer and exact callback/logout strings, rejecting a local-origin build for a staging manifest. This is a necessary consistency check, not proof of approved Cognito settings or live OAuth behavior.

The manifest records origin/callback/logout, candidate port8010, previous release
ID, file hashes and unresolved Linux/data/auth/resource/recovery gates. Rollback is
metadata only: no symlink change, Nginx reload, service restart, database restore or
Streamlit stop is attempted. A successful package is not deployment approval.

## Configuration, TLS and recovery evidence template

`infrastructure-evidence.example.json` consolidates outstanding named-resource
observations and approval gates. Null means unverified, not absent. Populate only
from existing authorized evidence or a separately approved bounded inspection.
Never collect private-key contents, environment values, credential URIs or raw
logs into this template. Record references/attestations instead. No discovery,
renewal rehearsal, backup, user creation, IAM change or infrastructure action is
performed by a template. Preserve existing ACME handling in the eventual reviewed
Nginx diff; do not assume a disabled named timer proves no alternative renewal.

Before staging: full required-store recovery, TLS renewal, Linux dependency/import
and Nginx/systemd parsing, dedicated identity/IMDS denial/coherent read-only
publication, peak capacity, real forecast availability, user-controlled live roles
and rollback acceptance remain explicit gates. No production setting is modified.

## Repeatable local checks and TLS boundary

`node scripts/check-deterministic-build.mjs --origin https://APPROVED_HOST` from
frontend builds twice into fresh temporary directories and compares every output
byte. It retains outputs and does not deploy. The candidate origin only binds public
callback/logout URLs; it does not register them with Cognito.

`venv/bin/python -B scripts/smoke_web_release.py --dist frontend/dist` from the
repository exercises seven SPA routes and callback fallback, API caching/readiness
and seven Analyst403s against synthetic in-process fixtures. No installed Nginx,
real browser layout or real Cognito identity is certified by this check.

For an owner-provided **public** leaf certificate only:
`venv/bin/python -B scripts/check_tls_certificate.py --certificate /ABSOLUTE/PUBLIC_LEAF_CERT.pem --hostname powerflowenergy.dev`.
It checks SAN hostname/time reserve offline, refuses private keys, and explicitly
does not certify chain trust, installed TLS or renewal. Do not inspect production
certificate/key paths or run Certbot under this local approval. A later renewal
review must identify the existing ACME method, saved pre/post/deploy hooks and
actual renewal mechanism before a separately approved dry run;
`--no-directory-hooks` alone does not neutralize all configured hooks.
