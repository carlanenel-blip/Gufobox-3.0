"""
tests/test_frontend_pr5.py — Smoke tests per PR 5: verifica i backend endpoint
usati dal frontend admin aggiornato in PR 5.

Copre:
- GET /api/admin/metrics  — endpoint usato da AdminDashboard (non /system/info)
- GET /api/diag/summary   — endpoint usato da AdminDashboard per lo stato operativo
- GET /api/diag/tools     — endpoint usato da AdminDiagnostics
- GET /api/system/standby — endpoint usato da AdminSystem per lo stato standby
- GET /api/auth/session   — endpoint usato da useAuth.restoreSession
- POST /api/auth/logout   — endpoint usato da useAuth.logoutAdmin
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def app():
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.diag import diag_bp
    from api.system import system_bp
    from api.auth import auth_bp

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-pr5-secret"
    flask_app.config["TESTING"] = True
    flask_app.config["SESSION_COOKIE_SECURE"] = False
    CORS(flask_app, supports_credentials=True)
    flask_app.register_blueprint(diag_bp, url_prefix="/api")
    flask_app.register_blueprint(system_bp, url_prefix="/api")
    flask_app.register_blueprint(auth_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")
    return flask_app


@pytest.fixture()
def client(app):
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def reset_auth_state():
    from core.state import state
    state.pop("auth", None)
    yield
    state.pop("auth", None)


# ─── AdminDashboard: usa /api/admin/metrics (non /system/info) ───────────────

def test_admin_metrics_endpoint_exists(client):
    """AdminDashboard v2 usa GET /admin/metrics — l'endpoint deve esistere."""
    rv = client.get("/api/admin/metrics")
    assert rv.status_code == 200


def test_admin_metrics_shape_for_dashboard(client):
    """Le chiavi attese da AdminDashboard devono essere presenti."""
    rv = client.get("/api/admin/metrics")
    data = rv.get_json()
    assert "cpu_temp_celsius" in data
    assert "ram" in data
    assert "disk" in data
    assert "uptime_seconds" in data
    ram = data["ram"]
    assert "used_mb" in ram
    assert "total_mb" in ram
    disk = data["disk"]
    assert "used_gb" in disk
    assert "total_gb" in disk


# ─── AdminDashboard + AdminDiagnostics: usa /api/diag/summary ────────────────

def test_diag_summary_endpoint_exists(client):
    rv = client.get("/api/diag/summary")
    assert rv.status_code == 200


def test_diag_summary_fields_for_dashboard(client):
    """I campi usati dai riquadri di stato della Dashboard devono essere presenti."""
    rv = client.get("/api/diag/summary")
    data = rv.get_json()
    # Usati dai status-item della dashboard
    assert "player_running" in data
    assert "player_mode" in data
    assert "ota_running" in data
    assert "ota_status" in data
    assert "active_jobs" in data
    assert "backup_count" in data
    assert "ok" in data
    assert "warnings" in data
    assert "in_standby" in data
    assert "api_version" in data


def test_diag_summary_ok_is_bool(client):
    data = client.get("/api/diag/summary").get_json()
    assert isinstance(data["ok"], bool)


def test_diag_summary_warnings_is_list(client):
    data = client.get("/api/diag/summary").get_json()
    assert isinstance(data["warnings"], list)


def test_diag_summary_active_jobs_is_int(client):
    data = client.get("/api/diag/summary").get_json()
    assert isinstance(data["active_jobs"], int)


# ─── AdminDiagnostics: usa /api/diag/tools ───────────────────────────────────

def test_diag_tools_endpoint_exists(client):
    rv = client.get("/api/diag/tools")
    assert rv.status_code == 200


def test_diag_tools_shape(client):
    data = client.get("/api/diag/tools").get_json()
    assert "tools" in data
    assert "all_critical_ok" in data
    assert isinstance(data["tools"], dict)


# ─── AdminSystem: usa GET /api/system/standby ────────────────────────────────

def test_system_standby_get_endpoint_exists(client):
    """AdminSystem usa GET /system/standby per rilevare la modalità standby."""
    rv = client.get("/api/system/standby")
    assert rv.status_code == 200


def test_system_standby_returns_in_standby_field(client):
    rv = client.get("/api/system/standby")
    data = rv.get_json()
    assert "in_standby" in data
    assert isinstance(data["in_standby"], bool)


# ─── useAuth: usa GET /api/auth/session e POST /api/auth/logout ──────────────

def test_auth_session_unauthenticated(client):
    """Senza login, la sessione non deve risultare autenticata."""
    rv = client.get("/api/auth/session")
    assert rv.status_code == 200
    data = rv.get_json()
    assert data.get("authenticated") is False


def test_auth_logout_endpoint_exists(client):
    """POST /auth/logout deve rispondere anche senza sessione attiva."""
    rv = client.post("/api/auth/logout", json={})
    assert rv.status_code == 200


def test_auth_full_cycle(client):
    """Login con PIN corretto → sessione autentica → logout → sessione non autentica."""
    # Login
    rv = client.post("/api/admin/login", json={"pin": "1234"})
    assert rv.status_code == 200
    token = rv.get_json().get("admin_token")
    assert token

    # Session check con token
    rv2 = client.get("/api/auth/session",
                     headers={"Authorization": f"Bearer {token}"})
    assert rv2.status_code == 200
    data2 = rv2.get_json()
    assert data2.get("authenticated") is True

    # Logout
    rv3 = client.post("/api/auth/logout",
                      headers={"Authorization": f"Bearer {token}"},
                      json={})
    assert rv3.status_code == 200

    # Session check dopo logout: token revocato → non autenticato
    rv4 = client.get("/api/auth/session",
                     headers={"Authorization": f"Bearer {token}"})
    data4 = rv4.get_json()
    assert data4.get("authenticated") is False


# ─── AdminSystem: usa POST /api/system con azione (non /system/reboot) ───────

def test_system_post_standby_action(client):
    """AdminSystem usa POST /system con {azione: standby} — non un endpoint dedicato."""
    rv = client.post("/api/system", json={"azione": "standby"})
    assert rv.status_code == 200
    assert rv.get_json().get("status") == "ok"


def test_system_post_unknown_action_returns_ok(client):
    """Azione sconosciuta non deve causare un 5xx."""
    rv = client.post("/api/system", json={"azione": "unknown_action"})
    assert rv.status_code == 200
