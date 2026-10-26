"""Strict actual-issuance offline evaluation of future-known 24-hour inputs.

This module never serves/publishes forecasts or changes a production release.
The existing exogenous Silver builder uses logical collection-cycle semantics;
those rows must NOT be treated as actual issue-time availability evidence.
Callers need separately evidenced actual issue and observation-availability
stamps. Historical target observations are labels only, never model features.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from models.next24h import HORIZONS, ISSUE_TIME
from processing.build_next24h_exogenous_silver import (
    EXOGENOUS_FEATURE_COLUMNS, TARGET_COLUMN,
)

ENTSOE_PREFIXES = (
    'load_forecast', 'generation_forecast', 'solar_forecast',
    'wind_offshore_forecast', 'wind_onshore_forecast',
)
SOURCE_PREFIXES = (*ENTSOE_PREFIXES, 'weather_forecast')
OBSERVED_AVAILABLE = 'issue_observations_available_at_utc'


def _utc(values: pd.Series, name: str) -> pd.Series:
    parsed = []
    for value in values:
        stamp = pd.Timestamp(value)
        if pd.isna(stamp) or stamp.tzinfo is None:
            raise ValueError(f'{name} requires nonmissing, timezone-aware timestamps.')
        parsed.append(stamp.tz_convert('UTC'))
    return pd.Series(pd.DatetimeIndex(parsed), index=values.index)


def validate_actual_issuance_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Fail closed on unproven availability; never floor acquisition timestamps.

    The declared availability fields must come from legitimate recorded source
    evidence. A passing structural check cannot certify external provenance.
    Returns a validated copy; does not mutate persisted datasets.
    """
    time_columns = [ISSUE_TIME, 'target_timestamp', 'issue_observed_timestamp', OBSERVED_AVAILABLE]
    for prefix in SOURCE_PREFIXES:
        time_columns.extend((f'{prefix}_collection_issue_time', f'{prefix}_acquired_at_utc'))
    time_columns.extend(f'{prefix}_source_created_at_utc' for prefix in ENTSOE_PREFIXES)
    required = {*time_columns, 'horizon_hours', TARGET_COLUMN, *EXOGENOUS_FEATURE_COLUMNS}
    missing = sorted(required - set(frame.columns))
    if missing or frame.empty:
        raise ValueError(f'Actual-issuance evaluation needs nonempty complete evidence; missing={missing}.')
    data = frame.copy()
    for column in time_columns:
        data[column] = _utc(data[column], column)
    issue = data[ISSUE_TIME]
    target = data['target_timestamp']
    if (issue != issue.dt.floor('h')).any() or (target != target.dt.floor('h')).any():
        raise ValueError('Actual issue and target times must be exact UTC hours.')
    horizons = pd.to_numeric(data['horizon_hours'], errors='raise')
    if not horizons.isin(HORIZONS).all() or not (target == issue + pd.to_timedelta(horizons, unit='h')).all():
        raise ValueError('Targets must be actual issue time plus horizons 1..24.')
    if data.duplicated([ISSUE_TIME, 'horizon_hours']).any():
        raise ValueError('Duplicate actual-issue/horizon rows are not permitted.')
    for _, group in data.groupby(ISSUE_TIME):
        if len(group) != 24 or set(group['horizon_hours']) != set(HORIZONS):
            raise ValueError('Each actual issue must contain all 24 horizons.')
    observed = data['issue_observed_timestamp']
    if (observed != observed.dt.floor('h')).any() or not (
        (observed + pd.Timedelta(hours=1) <= data[OBSERVED_AVAILABLE])
        & (data[OBSERVED_AVAILABLE] <= issue)
    ).all():
        raise ValueError('Observed hourly features must be complete and recorded available by actual issue.')
    # One consistent issue feature snapshot across its 24 target horizons.
    issue_feature_columns = [c for c in EXOGENOUS_FEATURE_COLUMNS
                             if not c.startswith('forecast_') and not c.startswith('target_')]
    for column in [*issue_feature_columns, 'issue_observed_timestamp', OBSERVED_AVAILABLE]:
        if (data.groupby(ISSUE_TIME)[column].nunique(dropna=False) != 1).any():
            raise ValueError('Each issue needs one consistent observed feature snapshot.')
    for prefix in SOURCE_PREFIXES:
        cycle, acquired = data[f'{prefix}_collection_issue_time'], data[f'{prefix}_acquired_at_utc']
        if not ((cycle <= acquired) & (acquired <= issue)).all():
            raise ValueError(f'{prefix} was not acquired by actual issue time.')
        if prefix in ENTSOE_PREFIXES and not (data[f'{prefix}_source_created_at_utc'] <= acquired).all():
            raise ValueError(f'{prefix} source creation follows acquisition.')
    numeric = [*EXOGENOUS_FEATURE_COLUMNS, TARGET_COLUMN]
    data[numeric] = data[numeric].apply(pd.to_numeric, errors='raise')
    if not np.isfinite(data[numeric].to_numpy(dtype=float)).all():
        raise ValueError('Evaluation features and labels must be finite.')
    # Calendar features are future-known, but must actually describe the target.
    expected_calendar = {
        'target_hour': target.dt.hour, 'target_day_of_week': target.dt.dayofweek,
        'target_month': target.dt.month, 'target_is_weekend': target.dt.dayofweek.isin([5, 6]).astype(int),
    }
    for column, expected in expected_calendar.items():
        if not (data[column] == expected).all():
            raise ValueError('Target calendar features do not match target timestamps.')
    return data.sort_values([ISSUE_TIME, 'horizon_hours']).reset_index(drop=True)


def purged_chronological_splits(frame, *, validation_start, test_start):
    """Embargo entire issue windows crossing split boundaries, not just rows."""
    data = validate_actual_issuance_rows(frame)
    boundaries = _utc(pd.Series([validation_start, test_start]), 'split boundary')
    validation_start, test_start = boundaries.tolist()
    if validation_start >= test_start:
        raise ValueError('Validation must precede the untouched test period.')
    last_target = data.groupby(ISSUE_TIME)['target_timestamp'].transform('max')
    issue = data[ISSUE_TIME]
    splits = {
        'train': data.loc[last_target < validation_start].copy(),
        'validation': data.loc[(issue >= validation_start) & (last_target < test_start)].copy(),
        'test': data.loc[issue >= test_start].copy(),
    }
    if any(part[ISSUE_TIME].nunique() < 2 for part in splits.values()):
        raise ValueError('Each split needs at least two complete actual issue windows.')
    return splits


def _observed_history(frame):
    if frame is None:
        return None
    required = {'timestamp', 'price_eur_mwh', 'available_at_utc'}
    if not required.issubset(frame.columns):
        raise ValueError('Seasonal baseline needs recorded observation availability.')
    data = frame.loc[:, sorted(required)].copy()
    for column in ('timestamp', 'available_at_utc'):
        data[column] = _utc(data[column], column)
    data['price_eur_mwh'] = pd.to_numeric(data['price_eur_mwh'], errors='raise')
    if ((data['timestamp'] != data['timestamp'].dt.floor('h')).any()
            or not (data['timestamp'] + pd.Timedelta(hours=1) <= data['available_at_utc']).all()
            or data.duplicated(['timestamp', 'available_at_utc']).any()
            or not np.isfinite(data['price_eur_mwh']).all()):
        raise ValueError('Seasonal baseline history is not valid as-of hourly evidence.')
    return data.sort_values('available_at_utc')


def _weekly_naive(rows, history):
    predictions = np.full(len(rows), np.nan)
    if history is None:
        return predictions
    for index, (_, row) in enumerate(rows.iterrows()):
        matching = history.loc[
            (history['timestamp'] == row['target_timestamp'] - pd.Timedelta(hours=168))
            & (history['available_at_utc'] <= row[ISSUE_TIME])
        ]
        if not matching.empty:
            # Select latest revision actually known at this issue, not final value.
            predictions[index] = float(matching.iloc[-1]['price_eur_mwh'])
    return predictions


def _metrics(actual, prediction):
    error = np.asarray(prediction, dtype=float) - np.asarray(actual, dtype=float)
    if not len(error):
        return {'mae': None, 'rmse': None, 'bias_predicted_minus_actual': None}
    return {'mae': float(np.abs(error).mean()), 'rmse': float(np.sqrt(np.square(error).mean())),
            'bias_predicted_minus_actual': float(error.mean())}


def evaluate_future_known_horizons(frame, estimator_factory, *, validation_start, test_start,
                                   observed_price_history=None):
    """Fit 24 independent offline estimators on train only; no model selection.

    Factory must return an unfitted independent estimator each time; scaling or
    preprocessing must be inside it so fitting cannot inspect held-out inputs.
    Returned metrics are offline evidence only, never an operational forecast.
    Persistence is always compared on identical pairs. Optional weekly naive
    requires exact-hour observation history with recorded availability; missing
    historical hours remain unavailable, with matched candidate metrics and
    sample counts so a partial baseline is not compared on a different sample.
    """
    splits = purged_chronological_splits(frame, validation_start=validation_start, test_start=test_start)
    history = _observed_history(observed_price_history)
    metrics, fitted_ids, models = [], set(), []
    features = list(EXOGENOUS_FEATURE_COLUMNS)
    for horizon in HORIZONS:
        model = estimator_factory(horizon)
        if id(model) in fitted_ids:
            raise ValueError('Each horizon requires an independent estimator instance.')
        fitted_ids.add(id(model))
        # Keep model refs alive so Python cannot recycle IDs between horizons.
        models.append(model)
        training = splits['train'].loc[lambda rows: rows['horizon_hours'] == horizon]
        model.fit(training[features], training[TARGET_COLUMN])
        for split in ('validation', 'test'):
            rows = splits[split].loc[lambda data: data['horizon_hours'] == horizon]
            actual = rows[TARGET_COLUMN].to_numpy(dtype=float)
            prediction = np.asarray(model.predict(rows[features]), dtype=float)
            if prediction.shape != actual.shape or not np.isfinite(prediction).all():
                raise ValueError('Each horizon must return one finite prediction per issue.')
            benchmarks = {
                'Candidate': prediction,
                'Persistence': rows['price_eur_mwh'].to_numpy(dtype=float),
                'Weekly seasonal naive': _weekly_naive(rows, history),
            }
            for model_name, values in benchmarks.items():
                available = np.isfinite(values)
                count = int(available.sum())
                enough = count >= 2
                matched = _metrics(actual[available], prediction[available]) if enough else {}
                metrics.append({
                    'split': split, 'model_name': model_name, 'horizon_hours': horizon,
                    'observations': count, 'eligible_issue_count': len(rows),
                    'status': 'Available' if enough else 'Insufficient available evidence',
                    **(_metrics(actual[available], values[available]) if enough else _metrics([], [])),
                    'candidate_mae_on_same_pairs': matched.get('mae'),
                    'candidate_rmse_on_same_pairs': matched.get('rmse'),
                })
    return pd.DataFrame(metrics), {
        'evaluation_type': 'offline_actual_issuance_exogenous_horizons',
        'production_promoted': False, 'operational_predictions_validated': False,
        'split_issue_counts': {name: int(rows[ISSUE_TIME].nunique()) for name, rows in splits.items()},
        'training_max_target': splits['train']['target_timestamp'].max().isoformat(),
        'validation_min_issue': splits['validation'][ISSUE_TIME].min().isoformat(),
        'validation_max_target': splits['validation']['target_timestamp'].max().isoformat(),
        'test_min_issue': splits['test'][ISSUE_TIME].min().isoformat(),
        'weekly_baseline_history_supplied': history is not None,
        'benchmark_policy': 'Persistence uses the available observed issue snapshot; weekly naive uses exact target minus168h and latest revision recorded available by issue. Missing evidence is never filled.',
        'provenance_limit': 'Validates supplied availability evidence, not authenticity of source timestamps.',
    }
