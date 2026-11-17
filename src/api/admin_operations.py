"""Bounded Admin operational evidence. Deliberately excludes raw text and config."""
from __future__ import annotations
import json
import math
import sqlite3
from .database import read_snapshot
from datetime import datetime
from typing import Literal
from fastapi import HTTPException
from pydantic import Field
from .market_data import PublicModel
from .operations_summary import _time, _code

Evidence = Literal['missing', 'empty', 'available']
STAGES = frozenset(['Total pipeline','ENTSO-E ingestion','Open-Meteo weather ingestion','Silver build','Silver validation','Gold build','Gold validation','One-hour model verification','One-hour predictions','Anomaly detection','Feature importance','Forecast-vintage collection','Forecast-vintage health monitoring','Next24h release verification','Next24h forecast generation','Next24h monitoring','Next24h model verification','Weather ingestion','Actual-vs-predicted report'])
COMPONENTS = frozenset(['pipeline','ENTSO-E generation','next24h forecast','ENTSO-E ingestion','Open-Meteo weather','storage','forecast-vintage collection','forecast-vintage health','ENTSO-E','email alerts'])
EVENTS = frozenset(['forecast_withheld','generation_repair','generation_revision','pipeline_failure','failure_alert_sent','source_gap','source_recovered','validation_failure','model_verification_failure','ingestion_failure','storage_failure','protected_historical_revision','failure_alert_suppressed','email_alert_failed','pipeline_stage_failed','data_quality_validation_failed','model_verification_failed','ingestion_failed'])
STATUSES = frozenset(['SUCCESS','FAILED','FAILURE','ERROR','RUNNING','WARNING','PASSED','ACTIVE','RESOLVED','RECORDED','SENT','UNKNOWN'])


class Run(PublicModel):
    timestamp: datetime | None
    status: str
    records_processed: int | None
    new_rows_ingested: int | None
    historical_prediction_rows: int | None
    forecast_status: str | None
    forecast_issue_time: datetime | None
    mode: str | None


class Incident(PublicModel):
    timestamp: datetime | None
    severity: Literal['INFO','WARNING','ERROR','UNKNOWN']
    component: str
    event: str
    status: str


class Timing(PublicModel):
    stage: str
    started_at: datetime | None
    ended_at: datetime | None
    seconds: float = Field(ge=0)
    status: str


class TimingSummary(PublicModel):
    latest_total_seconds: float = Field(ge=0)
    recent_average_seconds: float | None
    latest_forecast_seconds: float | None
    slowest_stage: str | None


class AdminOperations(PublicModel):
    run_evidence: Evidence
    incident_evidence: Evidence
    timing_evidence: Evidence
    runs: list[Run] = Field(max_length=100)
    incidents: list[Incident] = Field(max_length=100)
    latest_timings: list[Timing] = Field(max_length=200)
    timing_summary: TimingSummary | None
    provenance: str = 'Read-only operational SQLite: latest 100 runs/incidents and 200 timing records. Raw messages, identifiers, paths, credentials, configuration and details are intentionally excluded. Filters apply to this bounded recent history.'


def _count(value):
    return value if type(value) is int and 0 <= value <= 2_000_000_000 else None


def admin_operations(path):
    result = dict(run_evidence='missing', incident_evidence='missing', timing_evidence='missing', runs=[], incidents=[], latest_timings=[], timing_summary=None)
    if not path.is_file():
        return AdminOperations(**result)
    try:
        with read_snapshot(path) as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'pipeline_runs' in tables:
                rows = db.execute('SELECT run_time,status,records_processed,substr(message,1,65537) FROM pipeline_runs ORDER BY id DESC LIMIT 100').fetchall()
                result['run_evidence'] = 'available' if rows else 'empty'
                for stamp,status,count,message in rows:
                    try:
                        raw = json.loads(message) if isinstance(message,str) and len(message) <= 65536 else {}
                        raw = raw if isinstance(raw,dict) else {}
                    except ValueError:
                        raw = {}
                    result['runs'].append(Run(timestamp=_time(stamp),status=_code(status,STATUSES) or 'UNKNOWN',records_processed=_count(count),new_rows_ingested=_count(raw.get('new_rows_ingested')),historical_prediction_rows=_count(raw.get('predictions_generated')),forecast_status=_code(raw.get('next24h_forecast_status'), {'WITHHELD','UNAVAILABLE','GENERATED','UNCHANGED'}),forecast_issue_time=_time(raw.get('next24h_forecast_issue_time')),mode=_code(raw.get('mode'), {'historical','incremental','backfill','full','scheduled','INCREMENTAL','BACKFILL','FULL'})))
            if 'operational_incidents' in tables:
                rows = db.execute('SELECT timestamp_utc,severity,component,event_type,status FROM operational_incidents ORDER BY id DESC LIMIT 100').fetchall()
                result['incident_evidence'] = 'available' if rows else 'empty'
                result['incidents'] = [Incident(timestamp=_time(t),severity=_code(s,{'INFO','WARNING','ERROR'}) or 'UNKNOWN',component=_code(c,COMPONENTS) or 'Other recorded component',event=_code(e,EVENTS) or 'Other recorded event',status=_code(v,STATUSES) or 'UNKNOWN') for t,s,c,e,v in rows]
            if 'pipeline_stage_timings' in tables:
                rows = db.execute('SELECT run_id,stage_name,start_timestamp_utc,end_timestamp_utc,duration_seconds,status FROM pipeline_stage_timings ORDER BY id DESC LIMIT 200').fetchall()
                result['timing_evidence'] = 'available' if rows else 'empty'
                totals = [r for r in rows if r[1]=='Total pipeline']
                if totals:
                    latest = totals[0]
                    current = [r for r in rows if r[0]==latest[0]]
                    def duration(row):
                        value = float(row[4])
                        if not math.isfinite(value) or value < 0:
                            raise ValueError('Invalid timing')
                        return value
                    successful = [duration(r) for r in totals if r[5]=='SUCCESS'][:10]
                    forecast = [r for r in current if r[1]=='Next24h forecast generation']
                    stages = [r for r in current if r[1]!='Total pipeline']
                    slowest = max(stages,key=duration) if stages else None
                    result['timing_summary'] = TimingSummary(latest_total_seconds=duration(latest),recent_average_seconds=sum(successful)/len(successful) if successful else None,latest_forecast_seconds=duration(forecast[0]) if forecast else None,slowest_stage=_code(slowest[1],STAGES) or 'Other recorded stage' if slowest else None)
                    result['latest_timings'] = [Timing(stage=_code(r[1],STAGES) or 'Other recorded stage',started_at=_time(r[2]),ended_at=_time(r[3]),seconds=duration(r),status=_code(r[5],STATUSES) or 'UNKNOWN') for r in current]
                else:
                    # Partial instrumented run without a Total row remains viewable;
                    # its sum must never masquerade as the actual pipeline duration.
                    for r in rows:
                        value = float(r[4])
                        if not math.isfinite(value) or value < 0:
                            raise ValueError('Invalid timing')
                        result['latest_timings'].append(Timing(stage=_code(r[1],STAGES) or 'Other recorded stage',started_at=_time(r[2]),ended_at=_time(r[3]),seconds=value,status=_code(r[5],STATUSES) or 'UNKNOWN'))
        return AdminOperations(**result)
    except (sqlite3.Error, OSError, TypeError, ValueError, OverflowError):
        raise HTTPException(503, 'Operational evidence is invalid or temporarily unavailable.') from None
