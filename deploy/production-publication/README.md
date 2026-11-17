# Production publication feed

The existing worker remains the producer. This separate service reads its checkout at `/home/ec2-user/Electricity_Trading_Pipeline` and its Prefect API on loopback port 4200. It creates no Prefect tasks, calls no external providers, and runs no inference or model deserialization. The publisher cannot access the staging publication roots from its unit. The only writable persistent mount is `/srv/powerflow/production-published`. Native publication stores require root ownership. The unit uses a capability ceiling of `CAP_DAC_READ_SEARCH` and the existing `powerflow-api` group, whose GID must be 992 for the approved forecast helper. The API gets group read/search access and mounts this namespace read-only.

| Store | Producer inputs and validation |
| --- | --- |
| `data/current` | Silver market CSV and Raw ENTSO-E prices, historical next-hour actual/predicted CSV, anomaly report, frozen evaluation and feature importance, approved release metadata and artifacts, optional vintage/exogenous diagnostics and legacy realized CSV. Snapshot includes the operational SQLite database using the online backup API, integrity and schema checks, exact allowlist and file hashes. The bootstrap can show an existing historical report without implying a current next-hour forecast. |
| `forecast/current` | Five immutable inference receipt files, approved direct-model and feature-contract hashes, exact release-manifest hash, production scheduled Prefect run and inference task, and matching persisted forecast history. Existing validators check all 24 ordered target hours, finite values, completed price/load/generation quarters, and weather provenance and timing. The admission window is three hours from issue. API serving selects only remaining eligible targets within the issue-relative 24-hour horizon. No legacy forecast CSV or price-only fallback is installed. |
| `operations/current` | Latest due natural scheduled run and terminal state from Prefect, queried stage/task evidence, operational incidents and identity-matched persisted SQLite summary, plus receipt association. Delivery status reflects this production writer. If the latest due run is still active, retry at the next timer tick; the previous evidence ages normally. |
| `realized/current` | Receipt-verified forecast history matched to completed observed hourly prices over 30 days. The same captured Raw price bytes are used by both the data and realized stores. The API distinguishes insufficient pairs from a valid report with measurements. |

The publisher applies a 24-hour age limit to the latest completed Silver observation, three hours to the latest Raw price, and four hours to the latest completed realized-report observation. These are feed admission limits. Forecast eligibility uses the stricter receipt contract. Each store switches atomically and retains its immutable generations. The stores switch independently, so a partial publication is possible after a failure. A nonzero unit exit is an alert to inspect all four pointers. Independent forecast and operations expiry remain active.

At 11:01 UTC on 17 November 2026, EC2 still had Silver through 16 November 23:00 UTC and Raw prices through 17 November 09:45 UTC. The 10:45 UTC natural run was completed and withheld inference. The latest valid receipt was issued at 09:48 UTC for the 07:00 UTC issue. All 24 horizons and source manifest binding checked out, but its new-publication admission window had closed.

The exogenous quality JSON generated on 19 October 2026 is emitted by the standalone `src/processing/build_next24h_exogenous_silver.py` builder. The scheduled production path uses operational weather retrieval and the direct model's issue-hour eligibility checks (`src/scheduled_pipeline.py`, `src/models/next24h_production.py`). The writer preserves the report as dated diagnostic evidence. Its age does not independently establish current source coverage, and the writer does not rerun or redate it.

The 17 November EC2 inventory measured approximately 48 MiB of source inputs per data generation, before generated reports. Roughly 60 such generations would consume the retention budget. Provision at least 4 GiB usable for this feed and its spare capacity. The writer stops at a 3 GiB retention threshold or below 1 GiB filesystem free, retains rollback generations, and requires operator-approved cleanup of inactive releases before reaching either limit. Each individual source file/database is bounded at 64 MiB, and transient workspace can reach about 1 GiB under those bounds. Check actual inventory and headroom before enabling the timer. Assign a retention owner and act before the cap blocks refresh. The writer and candidate API have a combined configured memory ceiling of 896 MiB on the shared host. The last observation of about 934 MiB available leaves little margin at both ceilings. Record the first writer run’s peak and recheck host headroom before allowing overlap with the candidate and worker. The unit is limited to 384 MiB RAM, half a CPU and 150 seconds per attempt, with a 20-second SQLite backup deadline. A read-only SQLite source with committed WAL needs existing readable WAL/SHM files. SQLite opening/recovery failure under the read-only mount is a stop condition.

## Build the writer package after the manual Git checkpoint

Use the reviewed writer commit and keep the archive checksum separately. These commands select only tracked files and do not include a checkout, credentials or model data.
Include the reviewed operational evidence producer as a companion file. The writer verifies its pinned hash before use. Its adaptation is limited to the existing UTC issue-time spelling in the receipt and pipeline summary.

```bash
set -euo pipefail
writer_sha=$(git rev-parse HEAD)
git diff --exit-code HEAD -- deploy/production-publication src requirements deploy/staging/forecast-publication deploy/staging/operational-capture-correction-v1/operational_evidence_producer.py
work=$(mktemp -d)
mkdir "$work/bundle"
git archive "$writer_sha" src requirements/api.lock requirements/shared.txt \
  deploy/production-publication deploy/staging/forecast-publication/{automatic,prepare,publish}.py \
  deploy/staging/operational-capture-correction-v1/operational_evidence_producer.py |
  tar -xf - -C "$work/bundle"
(
  cd "$work/bundle"
  mv deploy/staging/forecast-publication/{automatic,prepare,publish}.py .
  mv deploy/staging/operational-capture-correction-v1/operational_evidence_producer.py .
  mv deploy/production-publication/{writer.py,*.service,*.timer,README.md} .
  printf '%s\n' "$writer_sha" > SOURCE-SHA
  find . -type f ! -name SHA256SUMS -print | LC_ALL=C sort | while IFS= read -r name; do
    shasum -a 256 "$name"
  done > SHA256SUMS
  COPYFILE_DISABLE=1 tar -czf "$work/$writer_sha.tar.gz" SOURCE-SHA SHA256SUMS \
    src requirements writer.py automatic.py prepare.py publish.py operational_evidence_producer.py README.md \
    powerflow-production-publication.{service,timer}
)
(cd "$work" && shasum -a 256 "$writer_sha.tar.gz" > RECEIPT.sha256)
printf '%s\n' "$work"
```

Keep the checksum receipt out of the upload's writable trust domain. Compare the independently retained receipt with the archive SHA-256 again on EC2. Before any install, extract to a private scratch directory and require the exact archive inventory. The following assumes `writer_sha` is the reviewed 40-character commit and `archive` points to the verified upload.

```bash
set -euo pipefail
[[ "$writer_sha" =~ ^[0-9a-f]{40}$ ]]
[[ "$archive_sha" =~ ^[0-9a-f]{64}$ ]] # from the independently retained receipt
test "$(sha256sum "$archive" | cut -d' ' -f1)" = "$archive_sha"
scratch=$(mktemp -d)
tar -tzf "$archive" > "$scratch/archive.inventory"
if grep -Eq '(^/|(^|/)\.\.?(/|$)|(^|/)(__MACOSX|\._[^/]*|\.DS_Store)(/|$))' "$scratch/archive.inventory"; then
  exit 1
fi
test -z "$(LC_ALL=C sort "$scratch/archive.inventory" | uniq -d)"
tar -tvzf "$archive" > "$scratch/archive.types"
awk '$1 !~ /^[-d]/ {exit 1}' "$scratch/archive.types"
mkdir "$scratch/bundle"
tar --no-same-owner --no-same-permissions -xzf "$archive" -C "$scratch/bundle"
cd "$scratch/bundle"
test "$(cat SOURCE-SHA)" = "$writer_sha"
sha256sum --strict -c SHA256SUMS
diff -u <(awk '{print $2}' SHA256SUMS | LC_ALL=C sort) \
  <(find . -type f ! -name SHA256SUMS -print | LC_ALL=C sort)
getent group powerflow-api | cut -d: -f3 | grep -x 992
id -u ec2-user | grep -x 1000
free -m
df -h /srv /opt
```

## Activate the publication writer only after separate authorization

Run from the verified scratch bundle on EC2. Ensure no existing production writer, namespace, units or deployment pointer would be overwritten. Confirm source paths are readable in the restricted service context and disk/RAM headroom covers the writer and candidate API.

```bash
root=/srv/powerflow/production-published
base=/opt/powerflow/production-publication
release="$base/$writer_sha"
unit=powerflow-production-publication
for path in "$root" "$base" /etc/systemd/system/"$unit".{service,timer}; do
  sudo -n test ! -e "$path"
  sudo -n test ! -L "$path"
done
sudo -n install -d -o root -g root -m 0755 "$base" "$release"
sudo -n cp -R SOURCE-SHA SHA256SUMS src requirements writer.py automatic.py prepare.py publish.py operational_evidence_producer.py \
  README.md "$unit".{service,timer} "$release/"
sudo -n chown -R root:root "$release"
sudo -n chmod -R go-w,a+rX "$release"
sudo -n bash -c 'cd "$1" && sha256sum --strict -c SHA256SUMS' _ "$release"
sudo -n /usr/bin/python3.14 -m venv "$release/venv"
sudo -n "$release/venv/bin/python" -m pip install -r "$release/requirements/api.lock"
sudo -n "$release/venv/bin/python" -m pip check
sudo -n ln -s "$release" "$base/current"
sudo -n install -d -o root -g powerflow-api -m 2750 "$root" \
  "$root"/{data,forecast,operations,realized}{,/releases}
printf 'powerflow-operational-evidence-v1\n' | sudo -n tee "$root/operations/contract" >/dev/null
printf 'powerflow-realized-performance-v1\n' | sudo -n tee "$root/realized/contract" >/dev/null
sudo -n chown root:powerflow-api "$root"/{operations,realized}/contract
sudo -n chmod 0640 "$root"/{operations,realized}/contract
sudo -n install -m 0644 "$release/$unit.service" "$release/$unit.timer" /etc/systemd/system/
sudo -n systemd-analyze verify /etc/systemd/system/"$unit".{service,timer}
sudo -n systemctl daemon-reload
sudo -n systemctl start "$unit.service"
sudo -n journalctl -u "$unit.service" -n 20 --no-pager
systemctl show "$unit.service" -p Result -p MemoryPeak -p ExecMainStatus
for directory in "$root" "$root"/{data,forecast,operations,realized}; do
  sudo -n -u powerflow-api test -r "$directory"
  sudo -n -u powerflow-api test -x "$directory"
  if sudo -n -u powerflow-api test -w "$directory"; then exit 1; fi
done
sudo -n -u powerflow-api env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$release/src" \
  "$release/venv/bin/python" -s "$release/writer.py" --check
```

The check must succeed from the API reader account. Record the four pointers, the time, and the forecast issue. If there are zero forecast rows, confirm the matching operational withholding/expiry evidence. This is evidence for a correct withheld state and is insufficient for live-primary cutover acceptance. Repeat after a new natural run produces a primary publication, check the same reader command, then start the timer and observe a scheduled tick:

```bash
sudo -n systemctl enable --now powerflow-production-publication.timer
systemctl list-timers powerflow-production-publication.timer --all
```

Configure the existing candidate proposal with the following values only during its separately authorized deployment. Keep its read-only mount and staging namespace masks.

```dotenv
POWERFLOW_API_DATA_ROOT=/srv/powerflow/production-published/data/current
POWERFLOW_FORECAST_PUBLICATION_ROOT=/srv/powerflow/production-published/forecast
POWERFLOW_OPERATIONAL_PUBLICATION_ROOT=/srv/powerflow/production-published/operations
POWERFLOW_REALIZED_REPORT_ROOT=/srv/powerflow/production-published/realized
POWERFLOW_PRICE_ONLY_FALLBACK=false
```

## Rollback

For the initial bootstrap the recorded previous state is no active pointers. Disable and stop only this timer and writer, then withdraw their pointers by renaming within each store. Keep the release directories and journal for diagnosis. Verify public routing still points to the legacy application if this is before cutover.

```bash
sudo -n systemctl disable --now powerflow-production-publication.timer
sudo -n systemctl stop powerflow-production-publication.service
stamp=$(date -u +%Y%m%dT%H%M%SZ)
for store in data forecast operations realized; do
  p="/srv/powerflow/production-published/$store/current"
  if sudo -n test -e "$p" || sudo -n test -L "$p"; then
    sudo -n mv -T "$p" "${p%/*}/.withdrawn-$stamp"
  fi
  sudo -n test ! -e "$p"
  sudo -n test ! -L "$p"
done
```

For later generations stop this writer, retain pointer values and use the last recorded writer release or a new validated one-shot. Do not manually repoint an expired forecast or infer consistency across the four stores from a matching timestamp. If the React apex has already been promoted and feed freshness cannot be re-established, use the separately approved apex route rollback to the existing Streamlit/API pair. Do not restore the source database from a derived publication snapshot.
