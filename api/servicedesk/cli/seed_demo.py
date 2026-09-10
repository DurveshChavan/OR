"""Seed the offline demo database.

    python -m api.servicedesk.cli.seed_demo

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

from api.servicedesk.db import models
from api.servicedesk.db.session import session_scope, database_url
from api.servicedesk.db.types import utcnow
from api.servicedesk.services import events, security
from api.servicedesk.services import tickets as ticket_service

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

#: The set is chosen so that one batch of recommendations reaches every
#: outcome the application can produce, rather than only the happy one. With
#: nine network slots across the roster, ten network tickets guarantee at least
#: one ``queued`` decision; INC-DEMO-0012 needs a skill nobody holds, which is
#: the ``no_eligible_agent`` outcome; INC-DEMO-0007 and INC-DEMO-0008 open far
#: enough in the past to be overdue when they are seeded, so Risk Radar has a
#: recovery group and the demo does not have to wait for one.
DEMO_TICKETS = (
    # reference, priority, skill, category, minutes since opening
    ("INC-DEMO-0001", 1, "network", "Network", 25),
    ("INC-DEMO-0002", 2, "database", "Database", 90),
    ("INC-DEMO-0003", 2, "network", "Network", 200),
    ("INC-DEMO-0004", 3, "hardware", "Hardware", 30),
    ("INC-DEMO-0005", 3, "desktop", "Desktop", 400),
    ("INC-DEMO-0006", 4, "network", "Network", 15),
    ("INC-DEMO-0007", 1, "network", "Network", 200),
    ("INC-DEMO-0008", 2, "network", "Network", 320),
    ("INC-DEMO-0009", 3, "network", "Network", 45),
    ("INC-DEMO-0010", 3, "network", "Network", 60),
    ("INC-DEMO-0011", 4, "network", "Network", 120),
    ("INC-DEMO-0012", 2, "mainframe", "Mainframe", 35),
    ("INC-DEMO-0013", 3, "network", "Network", 10),
    ("INC-DEMO-0014", 4, "network", "Network", 5),
)

#: Four machines, with the same honesty rule as everything else here: these are
#: illustrative figures carrying a source note that says so. A real deployment
#: replaces them with an asset-register export. The ages are chosen so the
#: advisor shows all three verdicts in one screen - WS-1004 is years past its
#: optimal replacement year, WS-1002 is within six months of it, and the other
#: two are not due.
#:
#: purchase 62,000, resale falling 30,000 / 22,000 / 15,000 / 9,000 / 5,000 and
#: running cost rising 4,000 / 7,000 / 12,000 / 20,000 / 32,000 put the lowest
#: average annual cost at year 3, which a reader can check by hand from the
#: table the screen prints.
DEMO_MACHINE_PURCHASE = 62000.0
DEMO_MACHINE_SCRAP = [30000.0, 22000.0, 15000.0, 9000.0, 5000.0]
DEMO_MACHINE_RUNNING = [4000.0, 7000.0, 12000.0, 20000.0, 32000.0]
DEMO_MACHINE_NOTE = (
    "illustrative asset-register figures; replace with the organisation's own "
    "purchasing and maintenance records"
)

DEMO_MACHINES = (
    # asset tag, location, type, age in months
    ("WS-1001", "HQ floor 2", "desktop", 8),
    ("WS-1002", "HQ floor 3", "laptop", 32),
    ("WS-1003", "Branch north", "desktop", 19),
    ("WS-1004", "Branch north", "desktop", 57),
)

#: Which seeded tickets a person has said are about which machine. Operator
#: statements, seeded so the advisor has evidence to count; nothing derives them.
DEMO_TICKET_MACHINE_LINKS = {
    "INC-DEMO-0004": "WS-1004",
    "INC-DEMO-0005": "WS-1004",
    "INC-DEMO-0009": "WS-1002",
}

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
        machines = {}
        for asset_tag, location, machine_type, age_months in DEMO_MACHINES:
            machine = models.Machine(
                asset_tag=asset_tag,
                location=location,
                machine_type=machine_type,
                age_months=age_months,
                age_recorded_at=now,
                purchase_cost=DEMO_MACHINE_PURCHASE,
                scrap_value_by_year_json=list(DEMO_MACHINE_SCRAP),
                running_cost_by_year_json=list(DEMO_MACHINE_RUNNING),
                source_note=DEMO_MACHINE_NOTE,
            )
            db.add(machine)
            db.flush()
            machines[asset_tag] = machine

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
            # The demo ships with committed artifacts, so a seeded ticket is a
            # scored ticket. If they are missing the seed still completes and
            # each ticket says so in its own history rather than silently
            # showing an empty risk column.
            ticket_service.score_ticket_in_transaction(
                db, users["manager"], ticket, allow_manual_fallback=True
            )
            asset_tag = DEMO_TICKET_MACHINE_LINKS.get(reference)
            if asset_tag:
                ticket.machine_id = machines[asset_tag].id
                events.record(
                    db,
                    ticket.id,
                    "TICKET_UPDATED",
                    actor_user_id=users["manager"].id,
                    payload={
                        "field": "machine_id",
                        "previous_machine_id": None,
                        "machine_id": ticket.machine_id,
                        "asset_tag": asset_tag,
                        "note": "seeded operator statement; nothing infers this link",
                    },
                )

        db.commit()
        return {
            "users": len(DEMO_USERS),
            "policies": len(DEMO_POLICIES),
            "agents": len(DEMO_AGENTS),
            "tickets": len(DEMO_TICKETS),
            "machines": len(DEMO_MACHINES),
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
