-- Generated from backend_health/verdict.py. Do not edit by hand;
-- run `python -m backend_health.verdict > sql/views/tenant_health_verdict.sql`
-- to regenerate after changing thresholds or the tenant registry.

CREATE OR REPLACE VIEW `{{dataset}}.tenant_health_verdict` AS
WITH thresholds AS (
  SELECT * FROM UNNEST([
    STRUCT('tenant-a' AS tenant_id, 800.0 AS latency_watch, 1500.0 AS latency_action, 70.0 AS cpu_watch, 90.0 AS cpu_action, 75.0 AS memory_watch, 90.0 AS memory_action, 1 AS bottleneck_watch, 3 AS bottleneck_action),
    STRUCT('tenant-b' AS tenant_id, 500.0 AS latency_watch, 1500.0 AS latency_action, 70.0 AS cpu_watch, 90.0 AS cpu_action, 75.0 AS memory_watch, 90.0 AS memory_action, 1 AS bottleneck_watch, 3 AS bottleneck_action),
    STRUCT('tenant-c' AS tenant_id, 500.0 AS latency_watch, 1500.0 AS latency_action, 70.0 AS cpu_watch, 90.0 AS cpu_action, 75.0 AS memory_watch, 90.0 AS memory_action, 1 AS bottleneck_watch, 3 AS bottleneck_action),
    STRUCT('__default__' AS tenant_id, 500.0 AS latency_watch, 1500.0 AS latency_action, 70.0 AS cpu_watch, 90.0 AS cpu_action, 75.0 AS memory_watch, 90.0 AS memory_action, 1 AS bottleneck_watch, 3 AS bottleneck_action)
  ])
),
resolved AS (
  SELECT
    m.tenant_id,
    m.day,
    m.avg_p95_ms,
    m.max_cpu_percent,
    m.max_memory_percent,
    m.bottleneck_count,
    COALESCE(t.latency_watch, d.latency_watch) AS latency_watch,
    COALESCE(t.latency_action, d.latency_action) AS latency_action,
    COALESCE(t.cpu_watch, d.cpu_watch) AS cpu_watch,
    COALESCE(t.cpu_action, d.cpu_action) AS cpu_action,
    COALESCE(t.memory_watch, d.memory_watch) AS memory_watch,
    COALESCE(t.memory_action, d.memory_action) AS memory_action,
    COALESCE(t.bottleneck_watch, d.bottleneck_watch) AS bottleneck_watch,
    COALESCE(t.bottleneck_action, d.bottleneck_action) AS bottleneck_action
  FROM `{{dataset}}.daily_tenant_metrics` m
  LEFT JOIN thresholds t ON t.tenant_id = m.tenant_id
  CROSS JOIN (SELECT * EXCEPT (tenant_id) FROM thresholds WHERE tenant_id = '__default__') d
),
classified AS (
  SELECT
    *,
    CASE
      WHEN avg_p95_ms >= latency_action THEN 'action_needed'
      WHEN avg_p95_ms >= latency_watch THEN 'watch'
      ELSE 'healthy'
    END AS latency_status,
    CASE
      WHEN max_cpu_percent >= cpu_action THEN 'action_needed'
      WHEN max_cpu_percent >= cpu_watch THEN 'watch'
      ELSE 'healthy'
    END AS cpu_status,
    CASE
      WHEN max_memory_percent >= memory_action THEN 'action_needed'
      WHEN max_memory_percent >= memory_watch THEN 'watch'
      ELSE 'healthy'
    END AS memory_status,
    CASE
      WHEN bottleneck_count >= bottleneck_action THEN 'action_needed'
      WHEN bottleneck_count >= bottleneck_watch THEN 'watch'
      ELSE 'healthy'
    END AS bottleneck_status
  FROM resolved
)
SELECT
  tenant_id,
  day,
  CASE
    WHEN 'action_needed' IN UNNEST([latency_status, cpu_status, memory_status, bottleneck_status]) THEN 'action_needed'
    WHEN 'watch' IN UNNEST([latency_status, cpu_status, memory_status, bottleneck_status]) THEN 'watch'
    ELSE 'healthy'
  END AS verdict,
  ARRAY(
    SELECT reason FROM UNNEST([
      IF(latency_status != 'healthy', CONCAT('latency_p95_ms ', latency_status), NULL),
      IF(cpu_status != 'healthy', CONCAT('cpu_percent ', cpu_status), NULL),
      IF(memory_status != 'healthy', CONCAT('memory_percent ', memory_status), NULL),
      IF(bottleneck_status != 'healthy', CONCAT('bottleneck_count ', bottleneck_status), NULL)
    ]) AS reason
    WHERE reason IS NOT NULL
  ) AS reasons,
  avg_p95_ms,
  max_cpu_percent,
  max_memory_percent,
  bottleneck_count
FROM classified;
