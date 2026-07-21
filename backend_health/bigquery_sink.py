from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Protocol


class Sink(Protocol):
    """A destination for metric rows.

    `replace` must be idempotent for a `(table, tenant_id, collected_at)` window:
    re-running the same window replaces that window's rows rather than appending,
    so a re-run or backfill never duplicates data.
    """

    def replace(
        self, table: str, tenant_id: str, collected_at: datetime, rows: list[dict]
    ) -> int: ...


class JsonlSink:
    """Idempotent file sink: one JSON-lines file per table under a directory.

    Used by the demo so the pipeline runs end-to-end with no BigQuery. Replacing
    a window rewrites the file without that window's prior rows.
    """

    def __init__(self, directory: str | Path):
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, table: str) -> Path:
        return self._dir / f"{table}.jsonl"

    def replace(
        self, table: str, tenant_id: str, collected_at: datetime, rows: list[dict]
    ) -> int:
        path = self._path(table)
        stamp = collected_at.isoformat()

        kept = []
        if path.exists():
            for line in path.read_text().splitlines():
                if not line.strip():
                    continue
                existing = json.loads(line)
                if existing.get("tenant_id") == tenant_id and existing.get("collected_at") == stamp:
                    continue
                kept.append(existing)

        kept.extend(rows)
        path.write_text("".join(json.dumps(row) + "\n" for row in kept))
        return len(rows)


def _import_bigquery():
    try:
        from google.cloud import bigquery
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-bigquery is not installed; install the 'bigquery' extra "
            "(pip install -e '.[bigquery]') to use the BigQuery sink"
        ) from exc
    return bigquery


class BigQuerySink:
    """Idempotent BigQuery sink.

    For each window it DELETEs the existing `(tenant_id, collected_at)` rows and
    then loads the new rows with a load job. Load jobs (not streaming inserts)
    are used so the preceding DELETE always applies to committed data — streaming
    inserts sit in a buffer that cannot be deleted for ~90 minutes and would
    allow duplicates on a same-hour re-run.
    """

    def __init__(self, client, dataset: str):
        self._client = client
        self._dataset = dataset
        self._bq = _import_bigquery()

    def replace(
        self, table: str, tenant_id: str, collected_at: datetime, rows: list[dict]
    ) -> int:
        table_id = f"{self._dataset}.{table}"
        delete_sql = (
            f"DELETE FROM `{table_id}` "
            "WHERE tenant_id = @tenant_id AND collected_at = @collected_at"
        )
        job_config = self._bq.QueryJobConfig(
            query_parameters=[
                self._bq.ScalarQueryParameter("tenant_id", "STRING", tenant_id),
                self._bq.ScalarQueryParameter("collected_at", "TIMESTAMP", collected_at),
            ]
        )
        self._client.query(delete_sql, job_config=job_config).result()

        if rows:
            self._client.load_table_from_json(rows, table_id).result()
        return len(rows)


def get_sink(
    mode: str,
    *,
    directory: str | Path = "out",
    dataset: str | None = None,
) -> Sink:
    if mode == "demo":
        return JsonlSink(directory)
    if mode == "bigquery":
        if not dataset:
            raise ValueError("bigquery sink requires a dataset")
        bigquery = _import_bigquery()
        return BigQuerySink(bigquery.Client(), dataset)
    raise ValueError(f"unknown sink mode {mode!r}; expected 'demo' or 'bigquery'")
