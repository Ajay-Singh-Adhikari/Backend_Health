-- Generated from backend_health/bigquery_schema.py. Do not edit by hand;
-- run `python -m backend_health.bigquery_schema` to regenerate.

CREATE TABLE IF NOT EXISTS `{{dataset}}.latency_samples` (
  tenant_id STRING NOT NULL,
  collected_at TIMESTAMP NOT NULL,
  transaction_name STRING NOT NULL,
  p50_ms FLOAT64,
  p95_ms FLOAT64,
  p99_ms FLOAT64,
  throughput_rpm FLOAT64
)
PARTITION BY DATE(collected_at)
CLUSTER BY tenant_id;

CREATE TABLE IF NOT EXISTS `{{dataset}}.bottleneck_events` (
  tenant_id STRING NOT NULL,
  collected_at TIMESTAMP NOT NULL,
  transaction_name STRING NOT NULL,
  duration_ms FLOAT64,
  kind STRING NOT NULL
)
PARTITION BY DATE(collected_at)
CLUSTER BY tenant_id;

CREATE TABLE IF NOT EXISTS `{{dataset}}.resource_samples` (
  tenant_id STRING NOT NULL,
  collected_at TIMESTAMP NOT NULL,
  host STRING NOT NULL,
  cpu_percent FLOAT64,
  memory_percent FLOAT64
)
PARTITION BY DATE(collected_at)
CLUSTER BY tenant_id;
