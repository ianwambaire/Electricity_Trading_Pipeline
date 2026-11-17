# Fixed operational terminal-result log inspection

Authorization scope: only pipeline.log for the verified 2026-11-07 08:45 UTC
natural run and its 08:47:41–42 UTC operational terminal hook.

Reads the single verified production-root logs/pipeline.log inode with no-follow,
O_NOATIME, owner/group 1000, restrictive modes and before/after drift verification.
Parent traversal is anchored and no-follow. No log rotation files or other logs.
Timestamp-header seeking (max24 probes, total2MiB) selects only the fixed
08:47:30–08:48:00 UTC window, converted using reported system-local offset.
Only operational terminal-result or hook-exception records are projected. No raw
messages, logger names, unrelated log entries, private paths or secret values
are returned or persisted. Probes/selected range exist only transiently in memory.
A timestamp ordering/coverage problem fails closed; no fallback scan or retry.
The result carries temporal association explicitly: the legacy result line does
not include its flow UUID. System timezone observation is not proof of a distinct
worker TZ override at the historical execution time.

Reuses the SHA-bound one-attempt read-only supervisor and complete V5 verification
closure. V5 and the preceding diagnostic remain unchanged. No Prefect/AWS/source
requests, SQLite access, helper execution, publishing, installation or service
commands are called. Exactly one pinned SSH connection, 90s remote,150s local,
5s termination escalation. Private sanitized evidence only. No repair authorized.
