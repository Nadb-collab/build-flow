"""Command line entry point: `leadbot run --config config/business.toml [--loop] [--live]`."""

from __future__ import annotations

import argparse
import logging
import time

from .config import load_config
from .engine import Engine
from .google_lsa import LsaClient
from .notifier import Notifier
from .responder import Responder
from .store import Store


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="leadbot", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="answer new Google Local Services leads")
    run.add_argument("--config", default="config/business.toml")
    run.add_argument("--loop", action="store_true", help="keep polling instead of running one pass")
    run.add_argument("--live", action="store_true", help="actually send replies (overrides dry_run in config)")
    run.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config(args.config)
    s = cfg.settings
    dry_run = s.dry_run and not args.live

    engine = Engine(
        source=LsaClient.from_yaml(s.google_ads_config, s.customer_id, s.login_customer_id),
        responder=Responder(cfg.business, model=s.model, effort=s.effort),
        store=Store(s.db_path),
        notifier=Notifier(s.escalation_webhook_url),
        lookback_days=s.lookback_days,
        max_auto_replies_per_lead=s.max_auto_replies_per_lead,
        dry_run=dry_run,
    )
    logging.getLogger("leadbot").info("starting (dry_run=%s)", dry_run)

    while True:
        try:
            engine.run_once()
        except Exception:
            if not args.loop:
                raise
            logging.getLogger("leadbot").exception("pass failed")
        if not args.loop:
            return
        time.sleep(s.poll_interval_seconds)


if __name__ == "__main__":
    main()
