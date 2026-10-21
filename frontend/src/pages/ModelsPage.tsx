import { LinearInfluence } from '../components/data/LinearInfluence'
import { useServerAccount } from '../auth/serverAccountContext'
import { api } from '../api/client'
import { formatTime } from '../api/forecastState'
import { useApi } from '../hooks/useApi'
import { ApiPanel, Facts } from '../components/data/ApiPanel'
import { PageHeading } from '../components/ui/PageHeading'
import { Panel } from '../components/ui/Panel'

export function ModelsPage() {
  const server = useServerAccount()
  const models = useApi(api.models)
  return <><PageHeading category="Platform" title="Model Insights" description="Release-specific model identity, artifact availability, and historical evaluation evidence."/>
    <p className="data-note">The 24-hour production model and the separate one-hour model solve different tasks on different evaluation periods. Metrics below are not a head-to-head ranking or a guarantee of future accuracy.</p>
    <ApiPanel title="Public model summaries" state={models}>{data=><div className="model-cards">{data.models.map(model=><Panel key={model.key} title={model.key==='next24h'?'Production 24-hour model':'Separate one-hour model'} description={model.purpose}><div className="api-content"><Facts items={[
      ['Model',model.name ?? 'Metadata unavailable'],['Version',model.version ?? 'Not recorded'],['Release kind',model.release_kind ?? 'Not provided'],['Metadata status',model.metadata_status],['Artifact status',model.artifact_status.replaceAll('_',' ')],['Forecast horizon',model.key==='next24h'?'h+1 through h+24':'h+1'],['Feature count',model.feature_count ?? 'Not provided'],['Metadata created',formatTime(model.released_at_utc)],['Metadata provenance',model.metadata_provenance?.replaceAll('_',' ') ?? 'Not provided'],
    ]}/>{model.metadata_sha256 && <details className="metadata-digest"><summary>Metadata fingerprint (SHA-256)</summary><code>{model.metadata_sha256}</code></details>}
      {model.evaluations.map(e=><section key={e.split} className="evaluation"><h3>{e.split.replaceAll('_',' ')} evaluation</h3><Facts items={[["MAE (EUR/MWh)",e.mae.toFixed(2)],['RMSE (EUR/MWh)',e.rmse.toFixed(2)],['R²',e.r2.toFixed(3)],['Observations',e.observations],['Observation basis',e.observation_basis.replaceAll('_',' ')],['Period start',formatTime(e.period_start)],['Period end',formatTime(e.period_end)],['Period basis',e.period_basis.replaceAll('_',' ')],['Persistence RMSE (EUR/MWh)',e.persistence_rmse?.toFixed(2) ?? 'Not provided']]}/></section>)}
      <ul className="model-notes">{model.notes.map(note=><li key={note}>{note}</li>)}</ul></div></Panel>)}</div>}</ApiPanel>
    {server.account?.role === 'Admin' ? <LinearInfluence/> : <section className="restricted-section" aria-labelledby="linear-influence"><h2 id="linear-influence">One-hour Linear Regression — Feature Influence</h2><p>{server.loading ? 'Verifying server permissions…' : server.error ? 'Server permissions are unavailable. Retry account verification from My Profile.' : 'Admin permission required to view coefficient reports.'}</p><p>Access is enforced by FastAPI. Public release summaries remain available above.</p></section>}
  </>
}
