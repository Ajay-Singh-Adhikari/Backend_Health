-- Generated from backend_health/verdict.py. Do not edit by hand;
-- run `python -m backend_health.verdict --latest > sql/views/latest_tenant_verdict.sql` to regenerate.

CREATE OR REPLACE VIEW `{{dataset}}.latest_tenant_verdict` AS
SELECT * EXCEPT (row_num)
FROM (
  SELECT
    *,
    ROW_NUMBER() OVER (PARTITION BY tenant_id ORDER BY day DESC) AS row_num
  FROM `{{dataset}}.tenant_health_verdict`
)
WHERE row_num = 1;
