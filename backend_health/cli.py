import argparse
import logging

log = logging.getLogger("backend_health")

DEFAULT_CONFIG = "config/tenants.example.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backend_health",
        description="Pull New Relic APM metrics per tenant into BigQuery.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Pull metrics for active tenants and write to BigQuery.")
    run_p.add_argument(
        "--tenant",
        help="Run for a single tenant ID instead of every active tenant.",
    )
    run_p.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        help=f"Path to the tenant registry (default: {DEFAULT_CONFIG}).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = build_parser().parse_args(argv)

    if args.command == "run":
        scope = args.tenant or "all active tenants"
        log.info("run: scope=%s config=%s", scope, args.config)
        log.info("ingestion pipeline is not wired yet; scaffolding only")
        return 0

    return 1
