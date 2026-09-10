"""Rescore open tickets from the command line.

    python -m api.servicedesk.cli.rescore_open_tickets --username manager.demo

It runs the same service function the manager-only endpoint runs, so the two can
never diverge, and it insists on a real user: an event whose actor is unknown is
not an audit record, and a maintenance script is not an exception to that.

This is also the harness the performance test drives, which is why it reports
elapsed milliseconds.
"""
import argparse
import sys
import time

from sqlalchemy import select

from api.servicedesk.db import models
from api.servicedesk.db.session import database_url, session_scope
from api.servicedesk.errors import ApiError
from api.servicedesk.services import decisions as decision_service


def run(username: str, only_stale: bool = False, stale_after_minutes: int = 5) -> dict:
    """Rescore and return the summary plus how long the whole path took."""
    db = session_scope()
    try:
        actor = db.scalar(
            select(models.User).where(models.User.username == username.strip().lower())
        )
        if actor is None:
            raise SystemExit("no user named %r; rescore needs a real actor" % username)
        if actor.role != "manager":
            raise SystemExit(
                "%s is a %s; rescore is a manager action" % (username, actor.role)
            )
        started = time.perf_counter()
        summary = decision_service.rescore(
            db, actor, only_stale=only_stale, stale_after_minutes=stale_after_minutes
        )
        db.commit()
        summary["elapsed_ms"] = (time.perf_counter() - started) * 1000.0
        return summary
    except ApiError as error:
        db.rollback()
        raise SystemExit("%s: %s" % (error.code, error.message))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Rescore open tickets.")
    parser.add_argument("--username", default="manager.demo",
                        help="manager whose name goes on every event written")
    parser.add_argument("--only-stale", action="store_true",
                        help="skip tickets scored within the staleness window")
    parser.add_argument("--stale-after-minutes", type=int, default=5)
    args = parser.parse_args(argv)

    summary = run(args.username, args.only_stale, args.stale_after_minutes)
    print("rescored %s" % database_url())
    print("  considered %d" % summary["considered"])
    print("  rescored   %d" % summary["rescored"])
    print("  unchanged  %d" % summary["unchanged"])
    print("  elapsed    %.1f ms" % summary["elapsed_ms"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
