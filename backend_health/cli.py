import argparse
import logging
from datetime import datetime, timezone

from backend_health.bigquery_sink import get_sink
from backend_health.config import RegistryError, active_tenants, get_tenant, load_registry
from backend_health.credentials import get_backend
from backend_health.nerdgraph import get_source
from backend_health.pipeline import run as run_pipeline

log = logging.getLogger("backend_health")

DEFAULT_CONFIG = "config/tenants.example.yaml"
DEFAULT_SINK_DIR = "out"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backend_health",
        description="Pull New Relic APM metrics per tenant into BigQuery.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_config_arg(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--config",
            default=DEFAULT_CONFIG,
            help=f"Path to the tenant registry (default: {DEFAULT_CONFIG}).",
        )

    run_p = sub.add_parser("run", help="Pull metrics for active tenants and write to BigQuery.")
    run_p.add_argument(
        "--tenant",
        help="Run for a single tenant ID instead of every active tenant.",
    )
    run_p.add_argument(
        "--source",
        choices=("demo", "nerdgraph"),
        default="demo",
        help="Metrics source: 'demo' (synthetic, no network) or 'nerdgraph' (live).",
    )
    run_p.add_argument(
        "--sink",
        choices=("demo", "bigquery"),
        default="demo",
        help="Where rows are written: 'demo' (local JSONL under --sink-dir) or 'bigquery'.",
    )
    run_p.add_argument(
        "--sink-dir",
        default=DEFAULT_SINK_DIR,
        help=f"Directory for the demo sink's JSONL files (default: {DEFAULT_SINK_DIR}).",
    )
    run_p.add_argument("--dataset", help="BigQuery dataset (required when --sink=bigquery).")
    add_config_arg(run_p)

    tenants_p = sub.add_parser("tenants", help="List tenants in the registry.")
    add_config_arg(tenants_p)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = build_parser().parse_args(argv)

    if args.command == "run":
        return _run(args)

    if args.command == "tenants":
        return _tenants(args)

    return 1


def _run(args: argparse.Namespace) -> int:
    try:
        tenants = load_registry(args.config)
    except RegistryError as exc:
        log.error("failed to load tenant registry: %s", exc)
        return 1

    if args.tenant:
        try:
            scope = [get_tenant(tenants, args.tenant)]
        except RegistryError as exc:
            log.error(str(exc))
            return 1
    else:
        scope = active_tenants(tenants)

    if not scope:
        log.info("no active tenants to run")
        return 0

    credentials = get_backend()
    source = get_source(args.source, credentials=credentials)
    sink = get_sink(args.sink, directory=args.sink_dir, dataset=args.dataset)

    # Truncated to the hour: re-running within the same hour is idempotent
    # (JsonlSink/BigQuerySink replace the window) and, for the demo source,
    # deterministic (seeded by tenant + hour).
    collected_at = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    summary = run_pipeline(scope, source, sink, collected_at)
    log.info(
        "run complete: %d ok, %d failed, %d rows written",
        summary.ok_count,
        summary.failed_count,
        summary.total_rows,
    )
    for result in summary.results:
        if not result.ok:
            log.error("tenant %s failed: %s", result.tenant_id, result.error)

    return 0 if summary.all_ok else 1


def _tenants(args: argparse.Namespace) -> int:
    tenants = load_registry(args.config)
    active = active_tenants(tenants)
    log.info("%d tenants (%d active) in %s", len(tenants), len(active), args.config)
    for tenant in tenants:
        log.info(
            "  %-10s status=%-11s account=%s",
            tenant.tenant_id,
            tenant.status,
            tenant.newrelic_account_id or "-",
        )
    return 0
