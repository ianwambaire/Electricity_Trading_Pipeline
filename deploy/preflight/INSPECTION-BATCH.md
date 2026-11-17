# Next read-only production inspection — one proposed authorization

**NOT EXECUTED.** Intended after accepted A3. Resource bindings below are historical verified values; stop on differences. No deployment, config write, reload, sudo, package install, SQL/data rows, credential/environment/log/argv dump, pipeline run, MFA/account changes or external HTTP.

Before execution, approve the script hash in `INSPECTION-SHA256.json`. Exactly one default-profile STS call, one strict SSH stdin session, and two projected Cognito client reads; no unrelated AWS/IAM enumeration. Export `AWS_MAX_ATTEMPTS=1` for CLI calls, no debug or automatic retries. Prefix each AWS CLI invocation with `venv/bin/python -B deploy/remediation/a3-bounded-local.py --` for a180second timeout and five-second kill escalation. Each invocation once, sequentially, stop on error or unexpected account/target/pool/client. Maximum four supervised operations, <=4×185seconds; remote payload also has60second internal/90second external deadline. No output automatically triggers changes.

1. On the Mac:

```sh
aws sts get-caller-identity --region us-east-1 --no-cli-pager
```

Require account`870755688674`. Root is acceptable **only for these approved read-only AWS calls** if the owner explicitly permits it; no identity switching or authentication-refresh retry in the batch. Confirm existing source profile—not the A3 role—is intended for this inspection.

2. One SSH session to previously verified EC2 `i-059e63a35a022cd0f`, `ec2-user@3.228.243.164`. Review `inspect-production-readonly.py`, hash locally, then send those unchanged bytes:

```sh
venv/bin/python -B deploy/remediation/a3-bounded-local.py -- ssh -F /dev/null -i /Users/iannganga/.ssh/powerflow-key.pem -o BatchMode=yes -o IdentitiesOnly=yes -o IdentityAgent=none -o StrictHostKeyChecking=yes -o UpdateHostKeys=no -o UserKnownHostsFile=/Users/iannganga/.ssh/known_hosts -o ForwardAgent=no -o RequestTTY=no -o ConnectTimeout=10 -o ServerAliveInterval=10 -o ServerAliveCountMax=3 -T ec2-user@3.228.243.164 '/usr/bin/timeout --signal=TERM --kill-after=5s 90s /home/ec2-user/Electricity_Trading_Pipeline/.venv-prod/bin/python -I -S -B -' < deploy/preflight/inspect-production-readonly.py
```

Approved payload scope would be:

- Parse `/etc/nginx/nginx.conf` plus at most16regular non-symlink `/etc/nginx/conf.d/*.conf`, <=64KiB each. Emit only public server names, known listen/upstream ports, SPA/API/ACME directive presence and security-header names. Raw file bodies, secret headers and private-key paths/contents are not printed. No include expansion or `nginx -T/-t` (those can access keys/configuration beyond this scope). Nonallowlisted upstreams are counted/redacted. Config text is read in memory and may contain sensitive directives, so explicit approval covers this fixed configuration-file read and filtered output; no `.env`, credential file or raw dump is permitted.
- Exact `/usr/bin/systemctl show` of nginx, existingAPI/Streamlit/Prefect/PostgreSQL and two named Certbot timers, using only the `PROPERTIES` allowlist in the script (no ExecStart/Environment/logs).
- `/usr/sbin/ss -ltnp '( sport = :8000 or sport = :8010 or sport = :8501 )'`: listener/process-name/PID metadata, not process arguments. Correlate8000PID with API MainPID; do not infer loaded revision from checkout alone.
- Four `/proc/meminfo` counters and statvfs on the known checkout; point-in-time only, no load/peak sampler.
- Fixed **public** certificate path `/etc/letsencrypt/live/powerflowenergy.dev/cert.pem`, only if its resolved target matches `/etc/letsencrypt/archive/powerflowenergy.dev/cert[0-9]+.pem`. Emit public DNS names/validity only; no private key or trust-chain claim.
- Read at most32KiB each from `/etc/crontab`, `/etc/cron.d/certbot`, `/etc/cron.d/certbot-renew`, emit only boolean Certbot-renew reference (or unknown). No other cron/home/profile search or raw lines.
- Four fixed loopback GETs: ports8000and8010, paths`/health`and`/ready`; HTTP status only, no response bodies, proxy environment, credentials or redirects.

Unknown/missing/unreadable files/services are unverified, not permission to elevate/search/fix. Resource/path/count/symlink/timeout failures stop. Component command failure is reported unknown; the operator must not treat the summary as passed installed acceptance. Capture stdout/stderr privately outside the repository; never publish raw policy/config/provider errors. A changed/unknown SSH key, absent runtime/timeout, forbidden privilege or unexpected payload result stops the batch with no retries/extra command. Normal SSH audit records occur.

3–4. Exact public projections for the two **existing** clients, no client-secret output:

```sh
aws cognito-idp describe-user-pool-client --user-pool-id us-east-1_NLoYFRvex --client-id 4t8s6a673a18qhbauqac8rhdcf --query 'UserPoolClient.{UserPoolId:UserPoolId,ClientId:ClientId,Callbacks:CallbackURLs,Logout:LogoutURLs,Flows:AllowedOAuthFlows,Scopes:AllowedOAuthScopes,Providers:SupportedIdentityProviders,OAuthEnabled:AllowedOAuthFlowsUserPoolClient}' --region us-east-1 --no-cli-pager
aws cognito-idp describe-user-pool-client --user-pool-id us-east-1_NLoYFRvex --client-id 5qa93km3lf2bbu3ffnrpea4r3g --query 'UserPoolClient.{UserPoolId:UserPoolId,ClientId:ClientId,Callbacks:CallbackURLs,Logout:LogoutURLs,Flows:AllowedOAuthFlows,Scopes:AllowedOAuthScopes,Providers:SupportedIdentityProviders,OAuthEnabled:AllowedOAuthFlowsUserPoolClient}' --region us-east-1 --no-cli-pager
```

Require exact expected pool/client IDs and review callback/logout/flow differences; no fix is authorized. The AWS API can return secret-bearing client data internally, but CLI projection excludes ClientSecret and no debug/raw response is retained. No new staging/production client is assumed to exist; these reads cannot verify a not-yet-created client or authorize callback changes.

**Limits:** this batch does not prove complete effective Nginx syntax/includes, installed kernel/cgroup isolation, peak capacity, live OIDC, renewal-hook safety, all cron mechanisms or PostgreSQL/Prefect/MLflow recovery. No Certbot dry-run/restart/reload, private key read or destructive check. Later staging activation still requires exact reviewed changes and acceptance. No policy/client callback modification follows automatically.
