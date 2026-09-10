"""Sign-in behaviour, including the things it must refuse to reveal."""
from api.servicedesk.services import auth, security


def test_login_sets_an_http_only_cookie_and_logout_revokes_it(client, signed_in):
    signed_in("dispatcher")
    cookie_header = client.cookies.get(auth.SESSION_COOKIE_NAME)
    assert cookie_header

    assert client.get("/api/me").status_code == 200

    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/me").status_code == 401


def test_login_response_never_contains_credentials(client, signed_in):
    signed_in("manager")
    body = client.get("/api/me").json()
    assert set(body["actor"]) == {"id", "username", "role"}
    assert "password" not in client.cookies.get(auth.SESSION_COOKIE_NAME)


def test_wrong_password_and_unknown_user_are_indistinguishable(client, db, demo_password):
    from api.servicedesk.db import models

    db.add(
        models.User(
            username="known.user",
            password_hash=security.hash_password(demo_password),
            role="dispatcher",
        )
    )
    db.commit()

    wrong_password = client.post(
        "/api/login", json={"username": "known.user", "password": "not-the-password"}
    )
    unknown_user = client.post(
        "/api/login", json={"username": "nobody.here", "password": "not-the-password"}
    )

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json()["error"]["code"] == unknown_user.json()["error"]["code"]
    assert wrong_password.json()["error"]["message"] == unknown_user.json()["error"]["message"]


def test_inactive_user_cannot_sign_in(client, db, demo_password):
    from api.servicedesk.db import models

    db.add(
        models.User(
            username="retired.user",
            password_hash=security.hash_password(demo_password),
            role="dispatcher",
            is_active=False,
        )
    )
    db.commit()

    response = client.post(
        "/api/login", json={"username": "retired.user", "password": demo_password}
    )
    assert response.status_code == 401


def test_username_comparison_is_case_insensitive(client, db, demo_password):
    from api.servicedesk.db import models

    db.add(
        models.User(
            username="mixed.case",
            password_hash=security.hash_password(demo_password),
            role="dispatcher",
        )
    )
    db.commit()

    response = client.post(
        "/api/login", json={"username": "Mixed.Case", "password": demo_password}
    )
    assert response.status_code == 200


def test_stored_password_is_a_hash_not_the_password(db, demo_password):
    from api.servicedesk.db import models

    hashed = security.hash_password(demo_password)
    db.add(models.User(username="hash.check", password_hash=hashed, role="dispatcher"))
    db.commit()

    assert demo_password not in hashed
    assert hashed.startswith("$argon2")
    assert security.verify_password(hashed, demo_password)
    assert not security.verify_password(hashed, demo_password + "x")


def test_session_row_stores_a_hash_of_the_cookie_not_the_cookie(client, db, signed_in):
    from api.servicedesk.db import models

    signed_in("dispatcher")
    token = client.cookies.get(auth.SESSION_COOKIE_NAME)
    stored_ids = [row.id for row in db.query(models.Session).all()]

    assert token not in stored_ids
    assert security.session_id_for(token) in stored_ids


def test_manager_only_route_rejects_a_dispatcher(client, signed_in):
    signed_in("dispatcher")
    response = client.post(
        "/api/agents", json={"display_name": "Resolver 99 (test)", "wip_limit": 2}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NOT_PERMITTED"


def test_error_responses_use_the_declared_envelope(client):
    response = client.get("/api/tickets")
    body = response.json()
    assert response.status_code == 401
    assert set(body) == {"error", "request_id"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["request_id"]
