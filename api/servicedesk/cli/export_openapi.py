"""Write the frozen API contract to docs/openapi.json.

    python -m api.servicedesk.cli.export_openapi

The file is generated from the running application rather than written by hand,
and a test asserts that regenerating it produces the committed bytes. A
hand-maintained contract drifts from the code silently; this one cannot.

What the committed file covers is the surface that exists: authentication,
tickets, events, agents, skills and SLA policies. The recommendation, rescore
and risk-radar endpoints of spec D.3 to D.6 are specified in prose and are added
to this artifact when they are built.
"""
import json
import os
import sys

from api.servicedesk.main import app

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
CONTRACT_PATH = os.path.join(PROJECT_ROOT, "docs", "openapi.json")


def contract_text() -> str:
    """The OpenAPI document as it should appear on disk."""
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main(argv=None) -> int:
    os.makedirs(os.path.dirname(CONTRACT_PATH), exist_ok=True)
    with open(CONTRACT_PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(contract_text())
    print("wrote %s" % CONTRACT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
