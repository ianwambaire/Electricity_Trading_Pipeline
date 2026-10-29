import {ApiError} from './client'
import type {ForecastReport,Next24Row} from './contracts'
import type {ApiState} from '../hooks/useApi'

export function publicationState<T extends ApiState<ForecastReport<Next24Row>>>(state:T, now:number):T {
  const publication=state.data?.publication
  if (publication && (now>Date.parse(publication.expires_at) || now<Date.parse(publication.issue_time))) {
    return {...state,data:null,error:new ApiError('Forecast withheld because the publication has expired.',503,'FORECAST_WITHHELD')}
  }
  return state
}
