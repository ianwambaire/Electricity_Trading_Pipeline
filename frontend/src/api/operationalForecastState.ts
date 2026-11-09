import type {Operations} from './restoration'
import {formatTime} from './forecastState'

// Recompute only the attested forecast availability. Never relabel historical
// execution health, operational evidence freshness or source completeness.
export function operationalForecastState(data:Operations|null,now:number):Operations|null{
 if(!data||data.forecast_status!=='VALID'||!data.forecast_expires_at)return data
 if(now>=Date.parse(data.forecast_expires_at))return {...data,forecast_status:'EXPIRED',forecast_reason:'The forecast horizon has expired. No historical forecast is substituted.',products:data.products.map(p=>p.product==='24-hour predictions'?{...p,status:'missing'}:p)}
 if(data.forecast_refresh_due_at&&now>=Date.parse(data.forecast_refresh_due_at))return {...data,forecast_reason:`Published forecast within its remaining horizon until ${formatTime(data.forecast_expires_at)}. Refresh delayed since ${formatTime(data.forecast_refresh_due_at)}; this is an older issue, not newly refreshed data. Elapsed targets are not live predictions.`}
 return data
}
