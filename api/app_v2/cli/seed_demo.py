"""Seed the offline demo database.

    python -m api.app_v2.cli.seed_demo

Everything created here is labelled as demo data, because the alternative is a
screenshot of invented numbers that later gets quoted as a result:

* the SLA policy rows carry the required source note saying they are
  illustrative and must be replaced with an organisation's own policy;
* agents are named fictional resolvers, not random draws, and their tickets are
  stored with ``source = "seed_demo"``;
* no ticket here comes from UCI-498, so nothing in the demo database can be
  mistaken for a measured result.

The command is idempotent: it refuses to seed a database that already has
users, so re-running it cannot quietly double a roster.
"""
import argparse
import sys
from datetime import timedelta

from sqlalchemy import func, select

from api.app_v2.db import models
from api.app_v2.db.session import session_scope, database_url
from api.app_v2.db.types import utcnow
from api.app_v2.services import events, security

DEMO_SOURCE_NOTE = "illustrative demo policy; replace with organisational SLA policy"

#: Priority 1 is the tightest deadline and the most expensive minute. The
#: numbers are a coherent demo scale in one currency unit per minute, not a
#: measurement of anyone's business.
DEMO_POLICIES = (
    # priority, target_minutes, breach, late, overdue_recovery, holding, threshold
    (1, 60, 20.0, 18.0, 24.0, 1.0, 0.50),
    (2, 240, 8.0, 7.0, 10.0, 0.6, 0.60),
    (3, 480, 3.0, 2.5, 4.0, 0.3, 0.70),
    (4, 1440, 1.0, 0.8, 1.4, 0.1, 0.80),
)

DEMO_AGENTS = (
    # display name, wip limit, [(skill, multiplier, is_primary)]
    ("Resolver 12 (demo)", 3, [("network", 0.9, True), ("hardware", 1.3, False)]),
    ("Resolver 17 (demo)", 4, [("network", 1.0, True)]),
    ("Resolver 21 (demo)", 2, [("database", 0.95, True), ("network", 1.4, False)]),
    ("Resolver 34 (demo)", 3, [("hardware", 1.0, True), ("desktop", 1.1, False)]),
)

DEMO_TICKETS = (
    # reference, priority, skill, category, minutes since opening
    ("INC-DEMO-0001", 1, "network", "Network", 25),
    ("INC-DEMO-0002", 2, "database", "Database", 90),
    ("INC-DEMO-0003", 2, "network", "Network", 200),
    ("INC-DEMO-0004", 3, "hardware", "Hardware", 30),
    ("INC-DEMO-0005", 3, "desktop", "Desktop", 400),
    ("INC-DEMO-0006", 4, "network", "Network", 15),
)

DEMO_USERS = (
    ("dispatcher.demo", "dispatcher", "local-demo-password"),
    ("manager.demo", "manager", "local-demo-password"),
)


def seed(force: bool = False) -> dict:
    """Write the demo rows. Returns a small count summary for the caller."""
    db = session_scope()
    try:
        existing_users = db.scalar(select(func.count()).select_from(models.User))
        if existing_users and not force:
            raise SystemExit(
                "database already contains %d user(s); refusing to seed on top of it "
                "(use --force only on a throwaway demo database)" % existing_users
            )

        users = {}
        for username, role, password in DEMO_USERS:
            user = models.User(
                username=username,
                password_hash=security.hash_password(password),
                role=role,
            )
            db.add(user)
            users[role] = user
        db.flush()

        for row in DEMO_POLICIES:
            priority, target, breach, late, overdue, holding, threshold = row
            db.add(
                models.SlaPolicy(
                    priority=priority,
                    target_minutes=target,
                    breach_penalty_per_minute=breach,
                    late_penalty_per_minute=late,
                    overdue_recovery_penalty_per_minute=overdue,
                    holding_cost_per_minute=holding,
                    escalation_threshold=threshold,
                    version=1,
                    source_note=DEMO_SOURCE_NOTE,
                )
            )
        db.flush()

        for display_name, wip_limit, skills in DEMO_AGENTS:
            agent = models.Agent(display_name=display_name, wip_limit=wip_limit)
            db.add(agent)
            db.flush()
            for skill, multiplier, is_primary in skills:
                db.add(
                    models.AgentSkill(
                        agent_id=agent.id,
                        skill=skill,
                        efficiency_multiplier=multiplier,
                        is_primary=is_primary,
                    )
                )
        db.flush()

        now = utcnow()
        policies = {p.priority: p for p in db.scalars(select(models.SlaPolicy)).all()}
        for reference, priority, skill, category, age_minutes in DEMO_TICKETS:
            opened_at = now - timedelta(minutes=age_minutes)
            ticket = models.Ticket(
                external_reference=reference,
                source="seed_demo",
                status="open",
                priority=priority,
                category=category,
                required_skill=skill,
                opened_at=opened_at,
                sla_due_at=opened_at + timedelta(minutes=policies[priority].target_minutes),
            )
            db.add(ticket)
            db.flush()
            events.record(
                db,
                ticket.id,
                "TICKET_CREATED",
                actor_user_id=users["manager"].id,
                payload={"source": "seed_demo", "seed_reference": reference},
            )

        db.commit()
        return {
            "users": len(DEMO_USERS),
            "policies": len(DEMO_POLICIES),
            "agents": len(DEMO_AGENTS),
            "tickets": len(DEMO_TICKETS),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Seed the offline demo database.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="seed even if users already exist; only for a throwaway database",
    )
    args = parser.parse_args(argv)
    counts = seed(force=args.force)
    print("seeded %s" % database_url())
    for name, count in counts.items():
        print("  %-9s %d" % (name, count))
    print("sign in as dispatcher.demo or manager.demo with password local-demo-password")
    return 0


if __name__ == "__main__":
    sys.exit(main())
