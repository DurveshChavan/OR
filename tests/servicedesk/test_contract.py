"""The committed contract matches the application, and the seed data is honest.

These tests need no database fixture, so they run once rather than per dialect.
"""
import json
import os

import pytest

from api.servicedesk.cli import export_openapi
from api.servicedesk.cli.seed_demo import DEMO_SOURCE_NOTE, DEMO_AGENTS, DEMO_POLICIES

REQUIRED_PATHS = {
    "/api/health",
    "/api/login",
    "/api/logout",
    "/api/me",
    "/api/tickets",
    "/api/tickets/{ticket_id}",
    "/api/tickets/{ticket_id}/events",
    "/api/agents",
    "/api/agents/{agent_id}",
    "/api/agents/{agent_id}/skills",
    "/api/sla-policies",
}


def test_committed_contract_matches_the_application():
    if not os.path.exists(export_openapi.CONTRACT_PATH):
        pytest.fail(
            "docs/openapi.json is missing; run "
            "python -m api.servicedesk.cli.export_openapi"
        )
    with open(export_openapi.CONTRACT_PATH, encoding="utf-8") as handle:
        committed = handle.read()
    assert committed == export_openapi.contract_text(), (
        "the API changed without regenerating the frozen contract; run "
        "python -m api.servicedesk.cli.export_openapi and record the change in STATE.md"
    )


def test_contract_covers_the_phase_one_surface():
    document = json.loads(export_openapi.contract_text())
    assert REQUIRED_PATHS <= set(document["paths"])


def test_every_seeded_policy_declares_itself_as_demo_configuration():
    assert all(len(row) == 7 for row in DEMO_POLICIES)
    assert DEMO_SOURCE_NOTE == (
        "illustrative demo policy; replace with organisational SLA policy"
    )


def test_seeded_agents_are_labelled_and_not_random():
    names = [name for name, _wip, _skills in DEMO_AGENTS]
    assert len(set(names)) == len(names)
    assert all("demo" in name.lower() for name in names)
