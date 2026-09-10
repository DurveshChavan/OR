"""Choose the incidents the offline demo is seeded with, and print them.

Run:  python scripts/select_demo_incidents.py

The demo database is seeded from real records in the UCI-498 incident log, not
from invented ones. This script is how those records were chosen, kept in the
repository so the choice is auditable rather than asserted. Its output is
pasted into ``api/servicedesk/cli/seed_demo.py`` as a literal table, which
keeps the seed command free of pandas and free of the data directory.

Two rules govern the choice.

**Only held-out rows.** The selection is restricted to ``split == "test"``, the
3,499 incidents the risk and duration models never saw during fitting. Seeding
from training rows would put the model's own memorised examples on screen and
call the result a prediction.

**The selection is deliberate, not random.** 3,333 of the 3,499 held-out
incidents are priority 3, so a random draw would show one tier and one outcome.
The demo has to reach every outcome the dispatcher can produce - an assignment,
a queued ticket when the tier runs out of capacity, and a refusal when no
resolver holds the required skill - so the tiers and the category mix are
chosen to force all three. Every field of each chosen incident is then taken
from the dataset unchanged.
"""
import pandas as pd

PARQUET = "data/processed/uci498/incidents_v1.parquet"

#: The category a ticket needs, and how many of each. "Category 42" is the
#: commonest in the held-out split, so it is the one the roster is skilled in
#: and the one that runs out of capacity.
BUSY = "Category 42"
#: No seeded resolver holds this one - it is what produces `no_eligible_agent`.
UNSTAFFED = "Category 23"

#: (priority label, category, minutes before "now" the ticket is placed).
#: The offsets are the demo's own: these incidents opened in 2016 and the
#: application measures a deadline against the clock, so each one is placed at
#: a stated offset inside the demo window. Two of them sit far enough back to
#: be overdue on arrival, which is what gives Risk Radar a recovery group.
PLAN = [
    ("1 - Critical", BUSY, 25),
    ("2 - High", BUSY, 90),
    ("2 - High", BUSY, 200),
    ("3 - Moderate", "Category 46", 30),
    ("3 - Moderate", "Category 26", 400),
    ("4 - Low", BUSY, 15),
    ("1 - Critical", BUSY, 200),
    ("2 - High", BUSY, 320),
    ("3 - Moderate", BUSY, 45),
    ("3 - Moderate", BUSY, 60),
    ("4 - Low", BUSY, 120),
    ("2 - High", UNSTAFFED, 35),
    ("3 - Moderate", "Category 53", 10),
    ("4 - Low", BUSY, 5),
]

PRIORITY_NUMBER = {
    "1 - Critical": 1,
    "2 - High": 2,
    "3 - Moderate": 3,
    "4 - Low": 4,
}


def main() -> int:
    held_out = pd.read_parquet(PARQUET).query("split == 'test'").sort_values("incident_id")
    taken = set()
    print("#: incident, priority, category, subcategory, location, contact, offset")
    print("DEMO_TICKETS = (")
    for priority_label, category, offset in PLAN:
        pool = held_out[
            (held_out.priority == priority_label)
            & (held_out.category == category)
            & (~held_out.incident_id.isin(taken))
        ]
        if pool.empty:
            # Priority 1 and 2 are rare, and rarer still inside one category.
            # Falling back on the tier alone keeps the tier coverage, which is
            # what the outcome depends on, and the printed row still carries
            # the incident's own category.
            pool = held_out[
                (held_out.priority == priority_label) & (~held_out.incident_id.isin(taken))
            ]
        row = pool.iloc[0]
        taken.add(row.incident_id)
        print(
            '    ("%s", %d, "%s", "%s", "%s", "%s", %d),'
            % (
                row.incident_id,
                PRIORITY_NUMBER[row.priority],
                row.category,
                row.subcategory,
                row.location,
                row.contact_type,
                offset,
            )
        )
    print(")")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
