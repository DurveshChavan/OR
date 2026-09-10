"""Seed the offline demo database.

    python -m api.servicedesk.cli.seed_demo

The tickets are real incidents from the UCI-498 incident management event log,
not invented ones. Three properties of that choice matter and are enforced here
rather than assumed:

* **held out.** Every seeded incident comes from the ``test`` split, the 3,499
  records the risk and duration models never saw while being fitted. A demo
  seeded from training rows would show the model its own memorised examples and
  present the answer as a prediction.
* **chosen, not sampled.** 3,333 of those 3,499 are priority 3, so a random draw
  shows one tier and one outcome. The set below is picked so that one batch of
  recommendations reaches every outcome the dispatcher can produce.
  ``scripts/select_demo_incidents.py`` is that selection, kept in the repository
  so the choice can be checked rather than taken on trust.
* **placed in the demo window.** The incidents opened in 2016 and the
  application measures a deadline against the clock, so each ticket is opened at
  a stated offset before now. That offset is the only figure here that does not
  come from the dataset, and it is recorded on the ticket's creation event.

Everything that is *not* a ticket is still illustrative and still carries a
required source note saying so: the SLA policy rows, the four resolvers and the
machine register, because UCI-498 has no SLA policy, no roster and no asset
table.

The command is idempotent: it refuses to seed a database that already has users,
so re-running it cannot quietly double a roster.
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

#: The roster is illustrative - UCI-498 has no resolver table, and the
#: assignment group it does carry was excluded from the model as leakage. The
#: skills are named after the dataset's own categories, which are anonymised at
#: source ("Category 42", not "Network"); renaming them to something that reads
#: better would be inventing the one field the dispatcher routes on.
#:
#: Nine slots across this roster hold Category 42 and ten Category 42 tickets
#: are seeded, so one of them is always queued rather than assigned.
DEMO_AGENTS = (
    # display name, wip limit, [(skill, multiplier, is_primary)]
    ("Resolver 12 (demo)", 3, [("Category 42", 0.9, True), ("Category 46", 1.3, False)]),
    ("Resolver 17 (demo)", 4, [("Category 42", 1.0, True)]),
    ("Resolver 21 (demo)", 2, [("Category 26", 0.95, True), ("Category 42", 1.4, False)]),
    ("Resolver 34 (demo)", 3, [("Category 46", 1.0, True), ("Category 53", 1.1, False)]),
)

#: Real held-out incidents, printed by ``scripts/select_demo_incidents.py``.
#: Priority, category, subcategory, location and contact type are the record's
#: own values, unchanged. The last column is the demo's own: how many minutes
#: before now the ticket is opened, because the record's 2016 timestamp would
#: read as ten years overdue against the clock.
#:
#: The mix is deliberate. Ten Category 42 tickets against nine Category 42 slots
#: guarantee a ``queued`` decision; INC0031021 is Category 23, which no seeded
#: resolver holds, and is the ``no_eligible_agent`` outcome; INC0030987 and
#: INC0032909 sit far enough back to be overdue on arrival, so Risk Radar has a
#: recovery group without anyone waiting for one.
DEMO_TICKETS = (
    # incident, priority, category, subcategory, location, contact, minutes ago
    ("INC0030036", 1, "Category 42", "Subcategory 31", "Location 45", "Phone", 25),
    ("INC0030553", 2, "Category 42", "Subcategory 183", "Location 188", "Phone", 90),
    ("INC0031735", 2, "Category 42", "Subcategory 29", "Location 204", "Phone", 200),
    ("INC0029952", 3, "Category 46", "Subcategory 233", "Location 161", "Phone", 30),
    ("INC0029939", 3, "Category 26", "Subcategory 164", "Location 82", "Phone", 400),
    ("INC0030139", 4, "Category 42", "Subcategory 223", "Location 204", "Phone", 15),
    ("INC0030987", 1, "Category 42", "Subcategory 223", "Location 204", "Phone", 200),
    ("INC0032909", 2, "Category 42", "Subcategory 223", "Location 161", "Phone", 320),
    ("INC0029946", 3, "Category 42", "Subcategory 223", "Location 42", "Phone", 45),
    ("INC0029947", 3, "Category 42", "Subcategory 223", "Location 108", "Phone", 60),
    ("INC0030347", 4, "Category 42", "Subcategory 223", "Location 204", "Phone", 120),
    ("INC0031021", 2, "Category 23", "Subcategory 174", "Location 143", "Phone", 35),
    ("INC0029953", 3, "Category 53", "Subcategory 178", "Location 204", "Phone", 10),
    ("INC0030422", 4, "Category 42", "Subcategory 223", "Location 143", "Phone", 5),
)

#: Where the seeded incidents come from, repeated into every seeded ticket's
#: creation event so the audit trail carries the provenance itself rather than a
#: document beside it claiming to.
DEMO_TICKET_PROVENANCE = (
    "UCI-498 incident management process enriched event log, held-out split; "
    "record fields unchanged, opened_at placed in the demo window"
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
    "INC0029952": "WS-1004",
    "INC0029939": "WS-1004",
    "INC0029946": "WS-1002",
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
        for row in DEMO_TICKETS:
            reference, priority, category, subcategory, location, contact, age_minutes = row
            opened_at = now - timedelta(minutes=age_minutes)
            ticket = models.Ticket(
                external_reference=reference,
                source="seed_demo",
                status="open",
                priority=priority,
                category=category,
                subcategory=subcategory,
                location=location,
                contact_type=contact,
                # The dataset has no resolver-skill column, so the category the
                # incident was actually filed under is what routing reads.
                required_skill=category,
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
                payload={
                    "source": "seed_demo",
                    "seed_reference": reference,
                    "provenance": DEMO_TICKET_PROVENANCE,
                    "opened_at_offset_minutes": age_minutes,
                },
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
