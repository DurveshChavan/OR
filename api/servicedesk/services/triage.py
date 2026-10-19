"""Triage: impact and urgency in, priority out, by the ITIL matrix.

``priority = min(4, impact + urgency - 1)``, with 1 the most urgent on every
scale. This is not a design choice: it is the matrix UCI-498 itself follows.
Every one of the seven impact/urgency pairs that occur in the 23,323 prepared
incidents maps to exactly one priority, and the formula reproduces all seven
(``tests/servicedesk/test_triage.py`` holds the table). The two pairs the log
never contains, (1, 3) and (3, 1), get 3 by extrapolating the same formula;
that is a stated assumption, not a measurement.

Why it matters for the risk model: impact and urgency are features it was
fitted on, and until a person supplies them the service desk had to pass them
as missing. Deriving priority from the pair, rather than taking all three
independently, means a scored ticket never carries a combination the log never
showed the model.

No model fills either field. Whether ticket text could suggest urgency was
tested and the answer was no (``docs/results/text-urgency-2026-10-15.md``).
"""
from api.servicedesk.errors import ApiError

#: UCI-498's own label form for both impact and urgency. The risk model's
#: one-hot encoder ignores an unknown label silently, so these strings must
#: match the training data exactly.
LEVEL_LABELS = {1: "1 - High", 2: "2 - Medium", 3: "3 - Low"}


def priority_from_impact_urgency(impact: int, urgency: int) -> int:
    """The ITIL priority matrix as UCI-498 applies it."""
    return min(4, impact + urgency - 1)


def resolve_priority(priority, impact, urgency):
    """The priority a ticket is stored with, and where it came from.

    With both impact and urgency known, priority is derived, and an explicit
    priority that disagrees is refused. Without the pair the operator's priority
    stands, which is also how every ticket before this change was made.
    """
    if impact is not None and urgency is not None:
        derived = priority_from_impact_urgency(impact, urgency)
        if priority is not None and priority != derived:
            raise ApiError(
                "PRIORITY_MATRIX_MISMATCH",
                "Impact %d and urgency %d give priority %d, not %d. Leave priority "
                "empty to derive it, or change impact or urgency."
                % (impact, urgency, derived, priority),
                status_code=422,
                details={"impact": impact, "urgency": urgency, "derived_priority": derived},
            )
        return derived, "impact_urgency_matrix"
    if priority is None:
        raise ApiError(
            "PRIORITY_REQUIRED",
            "Give a priority, or both impact and urgency so it can be derived.",
            status_code=422,
            details={"impact": impact, "urgency": urgency},
        )
    return priority, "operator"
