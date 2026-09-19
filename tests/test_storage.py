from pathlib import Path

import pytest

from storage.base import StorageError
from storage.config import StorageConfig
from storage.local import LocalStorageBackend
from storage.mappings import ARTIFACT_MAPPINGS, object_key
from storage.s3 import S3StorageBackend
from storage.sync import StorageSync
from scheduled_pipeline import _sync_storage_group


class MissingObject(Exception):
    def __init__(self):
        self.response = {
            "Error": {"Code": "404"},
            "ResponseMetadata": {"HTTPStatusCode": 404},
        }


class FakePaginator:
    def __init__(self, client):
        self.client = client

    def paginate(self, Bucket, Prefix):
        contents = [{"Key": key} for key in sorted(self.client.objects) if key.startswith(Prefix)]
        yield {"Contents": contents}


class FakeS3Client:
    def __init__(self, fail_upload=False):
        self.objects = {}
        self.fail_upload = fail_upload

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise MissingObject()
        item = self.objects[Key]
        return {"ContentLength": len(item["body"]), "Metadata": item["metadata"]}

    def upload_file(self, Filename, Bucket, Key, ExtraArgs=None):
        if self.fail_upload:
            raise RuntimeError("simulated upload failure")
        self.objects[Key] = {
            "body": Path(Filename).read_bytes(),
            "metadata": (ExtraArgs or {}).get("Metadata", {}),
        }

    def copy_object(self, Bucket, Key, CopySource, Metadata, MetadataDirective):
        original = self.objects[CopySource["Key"]]
        self.objects[Key] = {"body": original["body"], "metadata": Metadata}

    def delete_object(self, Bucket, Key, VersionId=None):
        self.objects.pop(Key, None)
        return {}

    def download_file(self, Bucket, Key, Filename):
        Path(Filename).write_bytes(self.objects[Key]["body"])

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return FakePaginator(self)


def test_local_backend_round_trip_and_metadata(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("durable", encoding="utf-8")
    backend = LocalStorageBackend(tmp_path / "store")

    assert backend.upload_file(source, "reports/test.txt") is True
    assert backend.upload_file(source, "reports/test.txt") is False
    assert backend.object_exists("reports/test.txt")
    assert backend.list_objects("reports/") == ["reports/test.txt"]
    assert backend.object_metadata("reports/test.txt")["ContentLength"] == 7

    restored = tmp_path / "restored.txt"
    backend.download_file("reports/test.txt", restored)
    assert restored.read_text(encoding="utf-8") == "durable"
    backend.delete_object("reports/test.txt")
    assert not backend.object_exists("reports/test.txt")


def test_s3_upload_is_verified_atomic_and_idempotent(tmp_path):
    source = tmp_path / "artifact.csv"
    source.write_text("timestamp,value\n2026-01-01,1\n", encoding="utf-8")
    client = FakeS3Client()
    backend = S3StorageBackend("bucket", "us-east-1", client=client)

    assert backend.upload_file(source, "gold/artifact.csv") is True
    assert backend.upload_file(source, "gold/artifact.csv") is False
    assert backend.object_exists("gold/artifact.csv")
    assert backend.list_objects("gold/") == ["gold/artifact.csv"]
    assert backend.object_metadata("gold/artifact.csv")["ContentLength"] == source.stat().st_size
    restored = tmp_path / "restored.csv"
    backend.download_file("gold/artifact.csv", restored)
    assert restored.read_bytes() == source.read_bytes()
    assert all(".uploading-" not in key for key in client.objects)


def test_s3_upload_failure_is_clear_and_leaves_no_final_object(tmp_path):
    source = tmp_path / "artifact.csv"
    source.write_text("value\n1\n", encoding="utf-8")
    backend = S3StorageBackend("bucket", "us-east-1", client=FakeS3Client(True))

    with pytest.raises(StorageError, match="simulated upload failure"):
        backend.upload_file(source, "silver/artifact.csv")
    assert not backend.object_exists("silver/artifact.csv")


def test_expected_prefix_mappings_are_exact():
    assert object_key("data/raw/entsoe/prices.csv") == "raw/entsoe/prices/prices.csv"
    assert object_key("data/raw/entsoe/load.csv") == "raw/entsoe/load/load.csv"
    assert object_key("data/raw/entsoe/generation.csv") == "raw/entsoe/generation/generation.csv"
    assert object_key("data/raw/weather/open_meteo_weather.csv") == "raw/weather/open_meteo_weather.csv"
    assert ARTIFACT_MAPPINGS["data/processed/silver_electricity_market_data.csv"].startswith("silver/")
    assert ARTIFACT_MAPPINGS["data/features/gold_model_features.csv"].startswith("gold/")
    assert object_key("data/reports/actual_vs_predicted.csv") == (
        "reports/predictions/actual_vs_predicted.csv"
    )
    assert object_key("data/reports/actual_vs_predicted.png") == (
        "reports/predictions/actual_vs_predicted.png"
    )
    assert object_key("data/reports/detected_anomalies.csv") == (
        "reports/anomalies/detected_anomalies.csv"
    )
    assert object_key("data/reports/anomaly_detection.png") == (
        "reports/anomalies/anomaly_detection.png"
    )
    assert object_key("data/reports/feature_importance.csv") == (
        "reports/monitoring/feature_importance.csv"
    )
    assert object_key("data/reports/feature_importance.png") == (
        "reports/monitoring/feature_importance.png"
    )


def test_local_mode_sync_is_a_noop(tmp_path):
    config = StorageConfig(backend="local", local_root=tmp_path)
    sync = StorageSync(config, tmp_path)

    result = sync.sync_group("raw")

    assert result.status == "NOT_REQUIRED"
    assert result.uploaded == []


def test_s3_sync_uploads_mapped_artifact(tmp_path):
    source = tmp_path / "data" / "processed" / "silver_electricity_market_data.csv"
    source.parent.mkdir(parents=True)
    source.write_text("timestamp,value\n2026-01-01,1\n", encoding="utf-8")
    client = FakeS3Client()
    backend = S3StorageBackend("bucket", "us-east-1", client=client)
    sync = StorageSync(StorageConfig("s3", "bucket"), tmp_path, backend=backend)

    result = sync.sync_group("silver")

    assert result.uploaded == ["silver/silver_electricity_market_data.csv"]


def test_s3_config_uses_provider_chain_without_credentials(monkeypatch):
    monkeypatch.setenv("POWERFLOW_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("POWERFLOW_S3_BUCKET", "example-bucket")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    config = StorageConfig.from_env()

    assert config.s3_bucket == "example-bucket"
    storage_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (Path(__file__).parents[1] / "src" / "storage").glob("*.py")
    ).lower()
    assert "aws_access_key_id" not in storage_source
    assert "aws_secret_access_key" not in storage_source


def test_failed_s3_sync_marks_operational_state_and_quality_result(monkeypatch):
    class FailedSync:
        config = StorageConfig("s3", "bucket")

        def sync_group(self, group):
            raise StorageError("network unavailable")

    recorded = []
    monkeypatch.setattr("scheduled_pipeline.initialize_database", lambda: None)
    monkeypatch.setattr(
        "scheduled_pipeline.log_data_quality_result",
        lambda **kwargs: recorded.append(kwargs),
    )
    state = {
        "s3_sync_status": "PENDING",
        "failed_upload_stage": None,
        "warnings": [],
        "objects_uploaded": [],
        "objects_unchanged": [],
    }

    with pytest.raises(StorageError, match="network unavailable"):
        _sync_storage_group(FailedSync(), state, "raw_entsoe", "Raw S3 sync")

    assert state["s3_sync_status"] == "FAILED"
    assert state["failed_upload_stage"] == "Raw S3 sync"
    assert recorded[0]["check_name"] == "s3_sync:raw_entsoe"
    assert recorded[0]["status"] == "FAILED"
