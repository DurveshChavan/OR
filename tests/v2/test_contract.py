"""The committed contract matches the application, and the seed data is honest.

These tests need no database fixture, so they run once rather than per dialect.
"""
import json
import os

import pytest

from api.app_v2.cli import export_openapi
from api.app_v2.cli.seed_demo import DEMO_SOURCE_NOTE, DEMO_AGENTS, DEMO_POLICIES

REQUIRED_PATHS = {
    "/api/v2/health",
    "/api/v2/login",
    "/api/v2/logout",
    "/api/v2/me",
    "/api/v2/tickets",
    "/api/v2/tickets/{ticket_id}",
    "/api/v2/tickets/{ticket_id}/events",
    "/api/v2/agents",
    "/api/v2/agents/{agent_id}",
    "/api/v2/agents/{agent_id}/skills",
    "/api/v2/sla-policies",
}


def test_committed_contract_matches_the_application():
    if not os.path.exists(export_openapi.CONTRACT_PATH):
        pytest.fail(
            "docs/openapi_v2.json is missing; run "
            "python -m api.app_v2.cli.export_openapi"
        )
    with open(export_openapi.CONTRACT_PATH, encoding="utf-8") as handle:
        committed = handle.read()
    assert committed == export_openapi.contract_text(), (
        "the API changed without regenerating the frozen contract; run "
        "python -m api.app_v2.cli.export_openapi and record the change in STATE.md"
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
