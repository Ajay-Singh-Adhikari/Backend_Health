-- Daily per-tenant rollup of the raw sample tables.
--
-- Snapshot metrics (latency percentiles, CPU/memory %) are aggregated with AVG
-- and MAX, never SUM — summing snapshots is meaningless and was a documented
-- footgun on the DB Health build. Bottlenecks are events, so they are COUNTed.
--
-- {{dataset}} is substituted with the target dataset at deploy time (same
-- convention as sql/schema.sql). This view feeds the verdict view (#11) and the
-- dashboard evidence charts (#10).

CREATE OR REPLACE VIEW `{{dataset}}.daily_tenant_metrics` AS
WITH latency AS (
  SELECT
    tenant_id,
    DATE(collected_at) AS day,
    AVG(p95_ms) AS avg_p95_ms,
    MAX(p95_ms) AS max_p95_ms,
    AVG(p99_ms) AS avg_p99_ms
  FROM `{{dataset}}.latency_samples`
  GROUP BY tenant_id, day
),
resources AS (
  SELECT
    tenant_id,
    DATE(collected_at) AS day,
    AVG(cpu_percent) AS avg_cpu_percent,
    MAX(cpu_percent) AS max_cpu_percent,
    AVG(memory_percent) AS avg_memory_percent,
    MAX(memory_percent) AS max_memory_percent
  FROM `{{dataset}}.resource_samples`
  GROUP BY tenant_id, day
),
bottlenecks AS (
  SELECT
    tenant_id,
    DATE(collected_at) AS day,
    COUNT(*) AS bottleneck_count
  FROM `{{dataset}}.bottlenecks`
  GROUP BY tenant_id, day
)
SELECT
  tenant_id,
  day,
  avg_p95_ms,
  max_p95_ms,
  avg_p99_ms,
  avg_cpu_percent,
  max_cpu_percent,
  avg_memory_percent,
  max_memory_percent,
  COALESCE(bottleneck_count, 0) AS bottleneck_count
FROM latency
FULL OUTER JOIN resources USING (tenant_id, day)
FULL OUTER JOIN bottlenecks USING (tenant_id, day);
