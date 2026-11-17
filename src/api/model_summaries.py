"""Allowlisted public metadata; never deserialize models or expose internal paths."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Literal

from .market_data import PublicModel


class Evaluation(PublicModel):
    split: Literal["validation", "test", "final_holdout"]
    mae: float
    rmse: float
    r2: float
    observations: int
    observation_basis: Literal["target_hours", "issue_horizon_pairs"]
    period_start: datetime | None
    period_end: datetime | None
    period_basis: Literal["target_time", "issue_time"]
    persistence_rmse: float | None = None


class ModelSummary(PublicModel):
    key: Literal["next24h", "one_hour"]
    name: str | None = None
    version: str | None = None
    release_kind: str | None = None
    purpose: str
    horizons_hours: list[int]
    metadata_status: Literal["available", "missing", "invalid"]
    metadata_provenance: Literal["release_manifest", "release_manifest_and_evaluation_report"] | None = None
    metadata_sha256: str | None = None
    released_at_utc: datetime | None = None
    feature_count: int | None = None
    artifact_status: Literal["missing", "present_not_integrity_verified", "integrity_verified", "integrity_mismatch", "unreadable"] = "missing"
    evaluations: list[Evaluation] = []
    notes: list[str]


class ModelsResponse(PublicModel):
    models: list[ModelSummary]


def _time(value) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Invalid timestamp")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Timezone required")
    return dt.astimezone(timezone.utc)


def _finite(value):
    # Reject booleans/strings in metadata rather than treating them as metrics.
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Invalid metric")
    return float(value)


def _evaluation(metrics, split, count, start, end, basis, persistence=None):
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("Invalid observation count")
    mae, rmse, r2 = (_finite(metrics[key]) for key in ("mae", "rmse", "r2"))
    if mae < 0 or rmse < 0:
        raise ValueError("Negative error")
    return Evaluation(split=split, mae=mae, rmse=rmse, r2=r2, observations=count,
                      observation_basis="target_hours" if basis == "target_time" else "issue_horizon_pairs",
                      period_start=_time(start) if start else None, period_end=_time(end) if end else None,
                      period_basis=basis, persistence_rmse=_finite(persistence) if persistence is not None else None)


@lru_cache(maxsize=8)
def _digest_version(path: Path, modified: int, size: int) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    stat = path.stat()
    if (stat.st_mtime_ns, stat.st_size) != (modified, size):
        raise ValueError("Artifact changed during verification")
    return digest.hexdigest()


def _digest(path):
    stat = path.stat()
    return _digest_version(path, stat.st_mtime_ns, stat.st_size)


def _artifacts(root: Path, key: str, manifest: dict) -> str:
    if key == "one_hour":
        paths = [root / "artifacts/models/final_gold_model.joblib", root / "artifacts/models/final_gold_model_features.joblib"]
        # This manifest does not supply artifact hashes. Existence is not a
        # guarantee of loadability or integrity; never unpickle for a public GET.
        return "present_not_integrity_verified" if all(p.is_file() for p in paths) else "missing"
    directory = root / "artifacts/models/releases/next24h"
    try:
        for filename, hash_key in (("next24h_model.joblib", "model_sha256"), ("next24h_feature_contract.joblib", "feature_contract_sha256")):
            path = directory / filename
            if not path.is_file():
                return "missing"
            if _digest(path) != manifest[hash_key]:
                return "integrity_mismatch"
        return "integrity_verified"
    except (OSError, KeyError, ValueError):
        return "unreadable"


def _summary(root: Path, key: str) -> ModelSummary:
    is24 = key == "next24h"
    base = dict(key=key, purpose="Next-24-hour price forecasting" if is24 else "Separate one-hour price model",
                horizons_hours=list(range(1, 25)) if is24 else [1])
    path = root / ("artifacts/models/releases/next24h/next24h_release_manifest.json" if is24 else "artifacts/models/final_model_release_manifest.json")
    if not path.is_file():
        return ModelSummary(**base, metadata_status="missing", notes=["Release metadata is not available locally."])
    try:
        with path.open("rb") as handle:
            raw = handle.read(128 * 1024 + 1)
        if len(raw) > 128 * 1024:
            raise ValueError("Metadata size limit")
        manifest = json.loads(raw)
        provenance = "release_manifest"
        if is24:
            if (manifest["release_type"] != "next24h_production" or manifest["horizons_hours"] != list(range(1, 25))
                or manifest["model_type"] != "Histogram Gradient Boosting (24 direct outputs)"
                or manifest["feature_count"] != 31):
                raise ValueError("Unexpected release")
            version = manifest["release_id"]
            if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", version):
                raise ValueError("Invalid release identifier")
            evaluations = []
            for split in ("validation", "test"):
                m = manifest[f"{split}_metrics"]
                evaluations.append(_evaluation(m, split, m["observations"], manifest[f"{split}_start"], None, "issue_time",
                                               manifest["persistence_test_metrics"]["rmse"] if split == "test" else None))
            name = manifest["model_type"]
            notes = ["Metrics count issue–horizon pairs; overlapping target windows are not independent samples.",
                     "Evaluation end times are not recorded in this release manifest.",
                     "Weaker performance during extreme price events. Future-horizon weather is not used.",
                     "Model artifact availability does not establish fresh forecast availability.",
                     "No production HGB feature-importance report is exposed by this endpoint."]
        else:
            if manifest["release_type"] != "final_2025_holdout_evaluation" or manifest["model"]["selected_model"] != "Ordinary Linear Regression" or manifest["model"]["feature_count"] != 31:
                raise ValueError("Unexpected release")
            holdout = manifest["final_holdout"]
            persistence = next(row["rmse"] for row in manifest["baseline_comparisons"] if row["baseline_name"] == "Persistence Baseline")
            evaluations = [_evaluation(holdout["metrics"], "final_holdout", holdout["rows"], holdout["target_date_range"]["start"], holdout["target_date_range"]["end"], "target_time", persistence)]
            report = root / "data/reports/final_holdout_metrics.csv"
            if report.is_file():
                if report.stat().st_size > 64 * 1024:
                    raise ValueError("Evaluation report size limit")
                with report.open(encoding="utf-8", newline="") as handle:
                    rows = list(csv.DictReader(handle))
                if len(rows) != 1:
                    raise ValueError("Unexpected evaluation report")
                row = rows[0]
                if row["model_name"] != "Ordinary Linear Regression" or int(row["holdout_rows"]) != holdout["rows"]:
                    raise ValueError("Evaluation report mismatch")
                for metric in ("mae", "rmse", "r2"):
                    if not math.isclose(float(row[metric]), holdout["metrics"][metric], rel_tol=1e-12, abs_tol=1e-12):
                        raise ValueError("Evaluation metric mismatch")
                if _time(row["holdout_start"]) != evaluations[0].period_start or _time(row["holdout_end"]) != evaluations[0].period_end:
                    raise ValueError("Evaluation period mismatch")
                provenance = "release_manifest_and_evaluation_report"
            name, version = manifest["model"]["selected_model"], None
            notes = ["This release has no explicit version identifier; release kind and creation time identify its metadata.",
                     "One-hour holdout metrics are not next24h performance and must not be compared across different evaluation periods.",
                     "Artifact presence is checked without deserialization; this manifest contains no artifact integrity hashes.",
                     "The existing coefficient-influence report belongs to this linear model, not the production HGB model."]
        return ModelSummary(**base, name=name, version=version, release_kind=manifest["release_type"],
                            metadata_status="available", metadata_provenance=provenance,
                            metadata_sha256=hashlib.sha256(raw).hexdigest(), released_at_utc=_time(manifest["created_at_utc"]),
                            feature_count=31, artifact_status=_artifacts(root, key, manifest), evaluations=evaluations, notes=notes)
    except (OSError, ValueError, TypeError, KeyError, StopIteration, csv.Error, OverflowError):
        return ModelSummary(**base, metadata_status="invalid", notes=["Release metadata is invalid, unreadable, or inconsistent with its evaluation report. No metrics are published for this entry."])


def model_summaries(root: Path | None) -> ModelsResponse:
    root = root or Path("/__powerflow_unconfigured_public_metadata__")
    return ModelsResponse(models=[_summary(root, "next24h"), _summary(root, "one_hour")])
