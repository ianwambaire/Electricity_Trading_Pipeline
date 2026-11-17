# R2 activation parser blocker — local fix only

One authorized read-only SSH inspection exited0. Detailed sanitized evidence: `R2-PARSER-DIAGNOSTIC-RESULTS.json`; private capture `/private/tmp/powerflow-activation-parser-diagnostic-8combdsq/`. No remote changes, Nginx tests/reload, candidate start/stop or activation retry occurred during diagnosis.

**Exact failure:** `/etc/nginx/conf.d/powerflow-staging-https.conf:41`, in http→server→location:

```nginx
proxy_set_header Connection "";
```

The private reviewer's parse() at line169 raised invalid_directive_end. The preceding token loop used `tokens[position[0]] not in '{};'`. In Python an empty string is a substring of every string; shlex correctly emitted the empty quoted argument as `''`, but this membership expression treated it as a delimiter. This is a custom-parser defect. Both retained native Nginx baseline and post-install tests report syntax is ok/test successful without warnings. No configuration repair is warranted.

**Stage reached:** candidate started, runtime gates and API checks passed,60-second observation completed, staging candidate/support/header configs installed, native post-install Nginx test passed. Custom review then failed before `reload-staging-routing`; no reload capture exists. Candidate config is on disk (SHA ba9cc88e8a9b8f9401a713ccc2289f1c4375aa734745a6bfdbb431ce240e96ba), but the reviewed attempt did not reload Nginx. Existing workers were not activated by that attempt. Do not rerun the initial activate() entry point: its one-attempt marker and placeholder guards intentionally reject this partial state.

**Current runtime:** FastAPI active/running as powerflow-api, bound127.0.0.1:8010, MainPID1824094, no restarts, health/ready200. MemoryCurrent64,405,504bytes; high402,653,184/max536,870,912/swap0 in both systemd and cgroup files. No OOM/high/max events. ProtectHome, ProtectSystem=strict, NoNewPrivileges, PrivateTmp/Devices and empty capabilities verified. IMDS IPv4/IPv6 denies configured; retained effective BPF ingress425/egress424 attachments match prior runtime gates (not formal bytecode verification).

Production API, Streamlit, Prefect worker/server and PostgreSQL MainPID/state match pre-install baselines. Production Nginx, public certificate and staging HTTP ACME hashes match. No MLflow changes made; no independent live MLflow-unit identity was available.

**Minimal LOCAL change:** replace only that membership comparison with explicit delimiter tokens:

```python
while position[0] < len(tokens) and tokens[position[0]] not in ('{', '}', ';'):
```

Corrected `activate-staging-https.py` SHA256: `c6d735d231943d2e3e4042ede969f838262eb3be2cac165fcc683d4c46e82d74`.

Original reviewed parser SHA remains `9c9173cf3f8da0e004dd30e16ca320f19ab860fa0770fa6a87414869b3efa6d4`; it is still the root-private remote artifact. No R2 bundle/artifact was rewritten. No include allowlist, file bound, conflict check, certificate check or permission check changed.

73 targeted local tests passed. New regressions cover empty double-quoted and single-quoted header values, the complete reviewed React proxy vhost with security headers, and rejection of a missing semicolon after an empty value. Existing conflict/include/traversal/symlink/limits/reload tests remain passing. Syntax passed. No live Nginx validation was executed in this diagnosis.

**Exact next authorization:** one bounded continuation, without restarting FastAPI, rewriting Nginx configs or rerunning installation/initial activation. It must hash-verify R2 artifacts and the one-line corrected reviewer, apply only that correction in memory (preserving original remote code/bundle), verify the installed candidate configuration and original production baselines, repeat candidate health/listener/cgroup/sandbox/BPF gates, run one bounded nginx -t, perform at most one graceful Nginx reload only after every gate passes, then check HTTPS/static assets/API/ACME and production preservation. Record a separate continuation audit marker; no retries, automatic rollback, Cognito/AWS change, source refresh or next24 activation. A hash-bound continuation command must cover this already-installed partial state, not bypass the old activation.started guard.
