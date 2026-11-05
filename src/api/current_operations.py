"""One request-local selection of sanitized current operational evidence.

No execution DB access. The only input is the dedicated immutable evidence store.
Admin projection is called exclusively behind the existing require_admin guard.
"""
from datetime import datetime, timezone

from shared.operational_evidence import view
from shared.operational_evidence_store import read_current

PUBLIC_FIELDS = ('status', 'evidence_id', 'observed_at', 'scheduled_at', 'fresh_until',
                 'current_execution', 'forecast_eligibility')


def current_selection(request, root, *, admin=False):
    if not hasattr(request.state, 'current_operational_evidence'):
        now = datetime.now(timezone.utc)
        selected = read_current(root, now=now, admin=True) if root is not None else view(now=now)
        request.state.current_operational_evidence = selected
    selected = request.state.current_operational_evidence
    result = {key: selected[key] for key in PUBLIC_FIELDS}
    if admin and selected['status'] == 'VALID':
        result['admin'] = selected['admin']
    return result
