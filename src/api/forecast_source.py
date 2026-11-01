"""Single read-only selection of active forecast evidence per request.

No response schema or persisted publication format is changed. Legacy snapshots
are a separate source mode, never a fallback for a configured publication.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fastapi import HTTPException
from shared import forecast_publication as contract
from .restricted_reports import ForecastProvenance
from .operations_summary import ProductSummary


@dataclass(frozen=True)
class PublicationSelection:
    status: Literal['VALID', 'EXPIRED', 'MISSING_PUBLICATION', 'WITHHELD']
    bundle: dict | None = None

    def require_valid(self):
        if self.bundle is None:
            raise HTTPException(503, detail={'code': 'FORECAST_WITHHELD'},
                                headers={'Cache-Control': 'no-store'})
        return self.bundle

    def match(self, issue: datetime | None, completed: datetime | None):
        bundle = self.require_valid()
        if ((issue is not None and issue != contract.time(bundle['forecasts'][0]['issue_time']))
                or (completed is not None and completed != contract.time(bundle['execution']['completed_at']))):
            raise HTTPException(409, 'The forecast changed. Refresh the forecast before requesting its evidence.',
                                headers={'Cache-Control': 'no-store'})

    def provenance(self):
        bundle = self.require_valid()
        return ForecastProvenance(
            issue_time=bundle['provenance']['issue_time'],
            issued_at_utc=bundle['execution']['issued_at'],
            issuance_evidence='available', provenance_evidence='available',
            weather_acquired_at_utc=bundle['provenance']['weather_acquired_at'],
            weather_source=bundle['provenance']['weather_source'],
            # No latest-source watermark is recorded by this public bundle.
            market_latest_complete_hour=None,
            note='Validated active publication: forecast and provenance share the same hash-bound bundle and inference. Issuance is the captured execution time, not a historical CSV lookup. Source watermarks are not inferred from the issue hour.')

    def operations(self, summary):
        if self.bundle is not None:
            issue = contract.time(self.bundle['provenance']['issue_time'])
            cutoff = issue + contract.MAX_AGE
            reason = f'Valid published forecast; issue {issue.isoformat()}, freshness cutoff {cutoff.isoformat()}.'
        else:
            reason = {
                'EXPIRED': 'The forecast publication has expired. No historical forecast is substituted.',
                'MISSING_PUBLICATION': 'No active forecast publication is available. Historical reports are not substituted.',
                'WITHHELD': 'Forecast publication withheld: integrity, completeness, eligibility or readability could not be verified.',
            }[self.status]
        products = [item.model_copy(update={'status': 'available' if self.bundle is not None else 'missing'})
                    if item.product == '24-hour predictions' else item for item in summary.products]
        if not any(item.product == '24-hour predictions' for item in products):
            products.append(ProductSummary(product='24-hour predictions', status='available' if self.bundle is not None else 'missing'))
        return summary.model_copy(update={
            'products': products,
            'health': 'Historical snapshot' if summary.latest_run_time is not None else 'Unavailable',
            'explanation': ('Recorded snapshot assessment: ' + summary.health + '. ' + summary.explanation
                            + ' This is not live pipeline health. Publication availability is assessed separately.'),
            'forecast_status': self.status, 'forecast_reason': reason,
            'forecast_reason_provenance': 'Active controlled publication, independently validated at request time; not the historical pipeline run status.',
            'completeness_note': 'Historical operational snapshot only. A successful recorded run does not establish forecast issuance. ' + summary.completeness_note,
        })


def select_publication(root):
    try:
        return PublicationSelection('VALID', contract.read_active(root))
    except contract.ExpiredPublication:
        return PublicationSelection('EXPIRED')
    except contract.MissingPublication:
        return PublicationSelection('MISSING_PUBLICATION')
    except contract.Withheld:
        return PublicationSelection('WITHHELD')
