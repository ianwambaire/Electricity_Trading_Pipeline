# Legacy PowerFlow implementation

This directory retains the earlier EIA/California pipeline, its SQLite-backed
model workflow, the previous dashboard, and related utilities for historical
reference. None of these modules are imported or executed by the primary
ENTSO-E Prefect pipeline.

The legacy code is not maintained as part of the current PowerFlow workflow.
Its existing relative imports are preserved. If historical investigation is
needed, run it with both the active and legacy source directories available:

```bash
PYTHONPATH=src:src/legacy python src/legacy/run_pipeline.py
```

The legacy API ingestion package can be invoked as a module:

```bash
PYTHONPATH=src/legacy python -m api_ingestion.run_api_ingestion
```

These commands may use historical data sources, schemas, and artifacts. They
are documentation aids, not supported entry points for the current pipeline.
