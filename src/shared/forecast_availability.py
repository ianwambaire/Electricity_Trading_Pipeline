"""Read-only API availability of an admitted forecast's remaining model horizon.

The separately pinned publisher/admission contract is unchanged. Its typed expiry
is raised only *after* full integrity and completeness verification at actual UTC.
This reader distinguishes that admission-age expiry from the prediction horizon;
it never validates at a backdated time or admits a publication.
"""
import datetime as dt
import os
from pathlib import Path
import re

from . import forecast_publication as contract

SERVING_HORIZON = dt.timedelta(hours=24)
AVAILABILITY_POLICY = 'ISSUE_HORIZON_V1'


def validate(raw, expected_hash, now=None):
    supplied_now = now
    now = now or dt.datetime.now(contract.UTC)
    try:
        # The original contract checks all hash, execution, input, feature and
        # model evidence before classifying admission-age expiry. All other
        # Withheld failures must propagate; no partial validation is accepted.
        try:
            bundle = contract.validate(raw, expected_hash, now)
        except contract.ExpiredPublication:
            bundle = contract.decode(raw)
        issue = contract.time(bundle['forecasts'][0]['issue_time'])
        completed = contract.time(bundle['execution']['completed_at'])
        contract.require(completed - issue <= contract.MAX_AGE)
        # Recheck actual time after validation; don't return a forecast that
        # crossed its last future target while integrity checks were running.
        checked_at = supplied_now if supplied_now is not None else dt.datetime.now(contract.UTC)
        contract.require(checked_at >= completed)
        if checked_at >= issue + SERVING_HORIZON:
            raise contract.ExpiredPublication('Forecast publication is withheld.')
        return bundle
    except contract.ExpiredPublication:
        raise
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError, IndexError) as error:
        raise contract.Withheld('Forecast publication is withheld.') from error


def read_active(root, now=None):
    """One controlled pointer snapshot; no historical scan, fallback or writes.

    Root ownership/permissions and the privileged publisher are prerequisites for
    trusting admission. V1 bundles do not record exact activation time; none is
    inferred from mtime, completion, API reads or this availability policy.
    """
    root = Path(root)
    try:
        try:
            root.lstat()
        except FileNotFoundError:
            raise contract.MissingPublication('Forecast publication is withheld.') from None
        for directory in (root, root/'releases'):
            contract.require(directory.is_dir() and not directory.is_symlink()
                             and directory.stat().st_uid in (0, os.geteuid())
                             and not directory.stat().st_mode & 0o022)
        try:
            target = os.readlink(root/'current')
        except FileNotFoundError:
            raise contract.MissingPublication('Forecast publication is withheld.') from None
        contract.require(re.fullmatch(r'releases/[0-9a-f]{64}', target) is not None)
        directory = root/target
        contract.require(directory.is_dir() and not directory.is_symlink()
                         and directory.stat().st_uid in (0, os.geteuid())
                         and not directory.stat().st_mode & 0o022)
        return validate(contract.safe_file(directory/'bundle.json'), target.split('/')[1], now)
    except (contract.ExpiredPublication, contract.MissingPublication):
        raise
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as error:
        raise contract.Withheld('Forecast publication is withheld.') from error
