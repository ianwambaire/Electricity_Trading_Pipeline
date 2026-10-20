// Runtime-validated public read models. Unknown fields are never retained.
export const generationKeys = ['biomass_mw', 'lignite_mw', 'gas_mw', 'hard_coal_mw', 'hydro_mw', 'nuclear_mw', 'solar_mw', 'wind_offshore_mw', 'wind_onshore_mw', 'wind_total_mw'] as const
export type GenerationKey = typeof generationKeys[number]
export interface MarketRow { timestamp: string; price_eur_mwh: number | null; load_mw: number | null; generation: Record<GenerationKey, number | null>; renewable_generation_mw: number | null; renewable_share: number | null }
export interface MarketCoverage { source: string; market_area: string; resolution: string; snapshot_id: string; row_count: number; first_observation: string | null; latest_observation: string | null; missing_hours_in_span: number; renewable_definition: string }
export interface MarketHistory { coverage: MarketCoverage; start: string | null; end: string | null; matched_rows: number; row_count: number; limit: number; offset: number; next_offset: number | null; observations: MarketRow[] }
export interface Evaluation { split: string; mae: number; rmse: number; r2: number; observations: number; observation_basis: string; period_start: string | null; period_end: string | null; period_basis: string; persistence_rmse: number | null }
export interface ModelSummary { key: 'next24h' | 'one_hour'; name: string | null; version: string | null; release_kind: string | null; purpose: string; horizons_hours: number[]; metadata_status: string; metadata_provenance: string | null; metadata_sha256: string | null; released_at_utc: string | null; feature_count: number | null; artifact_status: string; evaluations: Evaluation[]; notes: string[] }
export interface ModelsSummary { models: ModelSummary[] }

function object(value: unknown): Record<string,unknown> { if (!value || typeof value !== 'object' || Array.isArray(value)) throw Error('Expected object'); return value as Record<string,unknown> }
function text(value: unknown): string { if (typeof value !== 'string') throw Error('Expected text'); return value }
function finite(value: unknown): number { if (typeof value !== 'number' || !Number.isFinite(value)) throw Error('Expected finite number'); return value }
function count(value: unknown): number { const n = finite(value); if (!Number.isInteger(n) || n < 0) throw Error('Expected count'); return n }
function array(value: unknown): unknown[] { if (!Array.isArray(value)) throw Error('Expected array'); return value }
function nullable<T>(value: unknown, parse: (v: unknown) => T): T | null { return value === null ? null : parse(value) }
function time(value: unknown): string { const s = text(value); if (!/(Z|[+-]\d{2}:\d{2})$/.test(s) || !Number.isFinite(Date.parse(s))) throw Error('Expected timestamp'); return s }
function choice(value: unknown, options: readonly string[]): string { const s = text(value); if (!options.includes(s)) throw Error('Unexpected value'); return s }
function safeId(value: unknown): string { const s = text(value); if (!/^[A-Za-z0-9._-]{1,120}$/.test(s)) throw Error('Invalid identifier'); return s }
export function parseCoverage(value: unknown): MarketCoverage {
  const v = object(value)
  return { source: text(v.source), market_area: choice(v.market_area, ['DE-LU']), resolution: choice(v.resolution, ['hourly']), snapshot_id: safeId(v.snapshot_id), row_count: count(v.row_count), first_observation: nullable(v.first_observation,time), latest_observation: nullable(v.latest_observation,time), missing_hours_in_span: count(v.missing_hours_in_span), renewable_definition: text(v.renewable_definition) }
}
export function parseMarketHistory(value: unknown): MarketHistory {
  const v = object(value)
  const observations = array(v.observations).map(item => {
    const row = object(item); const g = object(row.generation)
    const generation = Object.fromEntries(generationKeys.map(key => [key, nullable(g[key],finite)])) as Record<GenerationKey,number|null>
    return { timestamp: time(row.timestamp), price_eur_mwh: nullable(row.price_eur_mwh,finite), load_mw: nullable(row.load_mw,finite), generation, renewable_generation_mw: nullable(row.renewable_generation_mw,finite), renewable_share: nullable(row.renewable_share,finite) }
  })
  const row_count = count(v.row_count); const limit = count(v.limit); const offset = count(v.offset); const matched = count(v.matched_rows)
  if (row_count !== observations.length || limit < 1 || limit > 2000 || row_count > limit || matched < row_count || observations.some((row,i) => i > 0 && Date.parse(row.timestamp) <= Date.parse(observations[i-1].timestamp))) throw Error('Invalid page')
  const next = nullable(v.next_offset,count)
  if (next !== null && (next !== offset + row_count || next >= matched || row_count === 0)) throw Error('Invalid pagination')
  return { coverage: parseCoverage(v.coverage), start: nullable(v.start,time), end: nullable(v.end,time), matched_rows: matched, row_count, limit, offset, next_offset: next, observations }
}
export function parseModels(value: unknown): ModelsSummary {
  const models = array(object(value).models).map(item => {
    const m = object(item); const key = choice(m.key,['next24h','one_hour']) as 'next24h'|'one_hour'
    const horizons = array(m.horizons_hours).map(count)
    if (horizons.join(',') !== (key === 'next24h' ? Array.from({length:24},(_,i)=>i+1).join(',') : '1')) throw Error('Invalid horizons')
    const evaluations = array(m.evaluations).map(item => {
      const e = object(item); const split = choice(e.split,key === 'next24h' ? ['validation','test'] : ['final_holdout'])
      const basis = choice(e.observation_basis,key === 'next24h' ? ['issue_horizon_pairs'] : ['target_hours'])
      const period = choice(e.period_basis,key === 'next24h' ? ['issue_time'] : ['target_time'])
      const mae = finite(e.mae); const rmse = finite(e.rmse)
      if (mae < 0 || rmse < 0) throw Error('Negative error')
      return { split, mae, rmse, r2: finite(e.r2), observations: count(e.observations), observation_basis: basis, period_basis: period, period_start: nullable(e.period_start,time), period_end: nullable(e.period_end,time), persistence_rmse: nullable(e.persistence_rmse,finite) }
    })
    return { key, name: nullable(m.name,v => choice(v,key === 'next24h' ? ['Histogram Gradient Boosting (24 direct outputs)'] : ['Ordinary Linear Regression'])), version: nullable(m.version,safeId), release_kind: nullable(m.release_kind,safeId), purpose: text(m.purpose), horizons_hours: horizons, metadata_status: choice(m.metadata_status,['available','missing','invalid']), metadata_provenance: nullable(m.metadata_provenance,v=>choice(v,['release_manifest','release_manifest_and_evaluation_report'])), metadata_sha256: nullable(m.metadata_sha256,v=>{ const s=text(v); if (!/^[a-f0-9]{64}$/.test(s)) throw Error('Invalid digest'); return s }), released_at_utc: nullable(m.released_at_utc,time), feature_count: nullable(m.feature_count,count), artifact_status: choice(m.artifact_status,['missing','present_not_integrity_verified','integrity_verified','integrity_mismatch','unreadable']), evaluations, notes: array(m.notes).map(text) }
  })
  if (models.length !== 2 || new Set(models.map(m=>m.key)).size !== 2) throw Error('Invalid model catalog')
  return { models }
}
