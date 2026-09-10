"""The client may only call endpoints the frozen contract declares.

pytest cannot render React, and a test that pretended to would prove nothing.
What it can do is read the one file the client is allowed to reach the API
through and check every path literal in it against ``docs/openapi_v2.json``.
That catches the failure that actually happens: a screen calling an endpoint
that was renamed, never built, or spelled differently in the browser than in
the router.

Two supporting checks are here for the same reason. ``credentials: "include"``
is what makes the session cookie travel, and a client without it signs in and
then gets a 401 on everything afterwards - a failure that looks like an auth
bug and is not. And the Vite proxy has to send ``/api/v2`` to the version-2
server before the broader ``/api`` rule sends it to the legacy one.
"""
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CLIENT_API = REPO_ROOT / "client" / "src" / "v2" / "lib" / "api.js"
VITE_CONFIG = REPO_ROOT / "client" / "vite.config.js"
CONTRACT = REPO_ROOT / "docs" / "openapi_v2.json"

#: `/api/v2/tickets/${id}/events` in the client, `/api/v2/tickets/{ticket_id}/events`
#: in the contract. Both are normalised to `/api/v2/tickets/{}/events` before
#: they are compared, because the parameter's name is not part of the route.
PATH_LITERAL = re.compile(r"[\"'`](/api/v2/[^\"'`]*)[\"'`]")
#: `/tickets/${id}` is a path parameter; the trailing `${toQuery(query)}` that
#: builds a query string is not part of the route at all.
PATH_SLOT = re.compile(r"(?<=/)\$\{[^}]*\}")
QUERY_SLOT = re.compile(r"(?<!/)\$\{[^}]*\}")
CONTRACT_SLOT = re.compile(r"\{[^}]*\}")


def normalise(path: str) -> str:
    path = path.split("?")[0]
    path = QUERY_SLOT.sub("", path)
    path = PATH_SLOT.sub("{}", path)
    return CONTRACT_SLOT.sub("{}", path).rstrip("/") or "/"


@pytest.fixture(scope="module")
def contract_paths() -> set:
    document = json.loads(CONTRACT.read_text(encoding="utf-8"))
    return {normalise(path) for path in document["paths"]}


@pytest.fixture(scope="module")
def client_source() -> str:
    return CLIENT_API.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def client_paths(client_source) -> set:
    return {normalise(match) for match in PATH_LITERAL.findall(client_source)}


def test_the_client_api_module_exists(client_source):
    assert "export const v2" in client_source


def test_every_path_the_client_calls_is_in_the_frozen_contract(
    client_paths, contract_paths
):
    assert client_paths, "no /api/v2 path literals were found in the client"
    undeclared = sorted(client_paths - contract_paths)
    assert undeclared == [], (
        "the client calls %s, which the committed contract does not declare"
        % undeclared
    )


def test_the_four_screens_can_reach_what_they_need(client_paths):
    """Named individually, because a missing one is a screen that cannot work."""
    required = {
        "/api/v2/login",
        "/api/v2/me",
        "/api/v2/health",
        "/api/v2/tickets",
        "/api/v2/tickets/{}",
        "/api/v2/tickets/{}/events",
        "/api/v2/tickets/rescore",
        "/api/v2/assignment-decisions",
        "/api/v2/assignment-decisions/{}",
        "/api/v2/assignment-decisions/{}/accept",
        "/api/v2/assignment-decisions/{}/override",
        "/api/v2/risk-radar",
        "/api/v2/agents",
        "/api/v2/sla-policies",
    }
    assert required <= client_paths


def test_the_client_sends_the_session_cookie(client_source):
    assert 'credentials: "include"' in client_source


def test_the_dev_proxy_routes_v2_before_the_legacy_prefix():
    config = VITE_CONFIG.read_text(encoding="utf-8")
    assert '"/api/v2"' in config, "the dev server has no version-2 proxy rule"
    assert config.index('"/api/v2"') < config.index('"/api":'), (
        "Vite matches proxy keys in insertion order, so /api/v2 must be "
        "registered before /api or every v2 call reaches the legacy server"
    )
