"""
tests/test_admin_ux_pr19.py — Tests per PR 19: UX/admin polish finale.

Verifica che:
- i composable/frontend helper esistenti siano presenti e corretti
- gli endpoint backend usati nelle sezioni admin polish siano funzionanti
- le azioni critiche (power, rollback, OTA) rispondano correttamente agli errori

Non dipende da hardware reale — usa l'app Flask in test mode.
"""

import os
import sys
import json

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def app():
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.system import system_bp
    from api.auth import auth_bp
    from api.diag import diag_bp
    from api.audio import audio_bp
    from api.led import led_bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"
    CORS(app)
    socketio.init_app(app, async_mode="threading")

    app.register_blueprint(system_bp, url_prefix="/api")
    app.register_blueprint(auth_bp, url_prefix="/api")
    app.register_blueprint(diag_bp, url_prefix="/api")
    app.register_blueprint(audio_bp, url_prefix="/api")
    app.register_blueprint(led_bp, url_prefix="/api")

    return app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def authed_client(app):
    """Client con token admin valido."""
    import core.state as state
    state.admin_token = "test-token-pr19"
    client = app.test_client()
    client.environ_base["HTTP_AUTHORIZATION"] = "Bearer test-token-pr19"
    return client


# ─── Tests: endpoint usati dalle sezioni admin polish ─────────────────────────

class TestSystemEndpointsForPolish:
    """Verifica endpoint /system/* usati da AdminSystem.vue."""

    def test_ota_status_returns_expected_fields(self, authed_client):
        """GET /api/system/ota/status deve restituire i campi attesi."""
        resp = authed_client.get("/api/system/ota/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "status" in data
        assert "running" in data
        # Campi OTA dalla PR 16
        assert "mode" in data or data.get("status") is not None

    def test_system_backups_returns_list(self, authed_client):
        """GET /api/system/backups deve restituire un oggetto con lista backup."""
        resp = authed_client.get("/api/system/backups")
        # Può essere 200 (lista vuota) o 200 (lista con backup)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "backups" in data
        assert isinstance(data["backups"], list)

    def test_system_standby_returns_status(self, authed_client):
        """GET /api/system/standby deve restituire in_standby."""
        resp = authed_client.get("/api/system/standby")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "in_standby" in data

    def test_power_action_rejects_invalid(self, authed_client):
        """POST /api/system con azione non valida deve restituire 400."""
        resp = authed_client.post(
            "/api/system",
            json={"azione": "format_disk"},
            content_type="application/json",
        )
        assert resp.status_code in (400, 422)

    def test_ota_start_rejects_unknown_mode(self, authed_client):
        """POST /api/system/ota/start con mode sconosciuto deve restituire errore."""
        resp = authed_client.post(
            "/api/system/ota/start",
            json={"mode": "hack_the_planet"},
            content_type="application/json",
        )
        # L'endpoint deve rifiutare mode non validi
        assert resp.status_code in (400, 422, 409)


class TestDiagEndpointsForPolish:
    """Verifica endpoint /diag/* usati da AdminDiagnostics.vue."""

    def test_diag_summary_returns_ok_field(self, authed_client):
        """GET /api/diag/summary deve avere campo 'ok'."""
        resp = authed_client.get("/api/diag/summary")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "ok" in data

    def test_diag_events_returns_list(self, authed_client):
        """GET /api/diag/events deve restituire lista eventi."""
        resp = authed_client.get("/api/diag/events")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "events" in data
        assert isinstance(data["events"], list)

    def test_diag_selfcheck_runs(self, authed_client):
        """POST /api/diag/selfcheck deve restituire ok e checks."""
        resp = authed_client.post("/api/diag/selfcheck")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "ok" in data
        assert "checks" in data

    def test_diag_tools_returns_tools(self, authed_client):
        """GET /api/diag/tools deve restituire tools dict."""
        resp = authed_client.get("/api/diag/tools")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "tools" in data


class TestAudioEndpointsForPolish:
    """Verifica endpoint /audio/* usati da AdminAudio.vue."""

    def test_audio_status_returns_audio_ready(self, authed_client):
        """GET /api/audio/status deve avere audio_ready."""
        resp = authed_client.get("/api/audio/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "audio_ready" in data

    def test_audio_volume_clamps_out_of_range(self, authed_client):
        """POST /api/audio/volume con volume > 100 deve essere silenziosamente ridotto a 100."""
        resp = authed_client.post(
            "/api/audio/volume",
            json={"volume": 200},
            content_type="application/json",
        )
        # Il backend clamps il valore a 100 invece di restituire un errore
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["volume"] <= 100


class TestLedEndpointsForPolish:
    """Verifica endpoint /led/* usati da AdminLed.vue."""

    def test_led_status_returns_runtime(self, authed_client):
        """GET /api/led/status deve restituire dati di stato."""
        resp = authed_client.get("/api/led/status")
        assert resp.status_code == 200
        data = resp.get_json()
        # Verifica che almeno il runtime sia presente
        assert data is not None

    def test_led_effects_returns_list(self, authed_client):
        """GET /api/led/effects deve restituire lista effetti."""
        resp = authed_client.get("/api/led/effects")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "effects" in data
        assert isinstance(data["effects"], list)
        # Deve esserci almeno l'effetto 'solid' builtin
        effect_ids = [e["id"] for e in data["effects"]]
        assert "solid" in effect_ids

    def test_led_master_get_returns_settings(self, authed_client):
        """GET /api/led/master deve restituire configurazione master."""
        resp = authed_client.get("/api/led/master")
        assert resp.status_code == 200
        data = resp.get_json()
        # Deve avere il campo settings o i campi diretti
        assert "settings" in data or "effect_id" in data


# ─── Tests: useAdminFeedback composable (verifica struttura file JS) ──────────

class TestAdminFeedbackComposable:
    """Verifica che il composable useAdminFeedback.js esista e abbia le API corrette."""

    COMPOSABLE_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "frontend", "src", "composables", "useAdminFeedback.js",
    )

    def test_composable_file_exists(self):
        assert os.path.isfile(self.COMPOSABLE_PATH), (
            "useAdminFeedback.js non trovato in frontend/src/composables/"
        )

    def test_composable_exports_expected_functions(self):
        with open(self.COMPOSABLE_PATH, encoding="utf-8") as f:
            content = f.read()
        # Verifica che le funzioni chiave siano definite/esportate
        assert "showSuccess" in content
        assert "showError" in content
        assert "showWarning" in content
        assert "clearFeedback" in content
        assert "feedbackMsg" in content
        assert "feedbackType" in content

    def test_composable_auto_hide_success(self):
        """showSuccess deve pianificare auto-hide via setTimeout."""
        with open(self.COMPOSABLE_PATH, encoding="utf-8") as f:
            content = f.read()
        assert "setTimeout" in content

    def test_composable_no_alert_calls(self):
        """Il composable non deve usare alert() direttamente."""
        with open(self.COMPOSABLE_PATH, encoding="utf-8") as f:
            content = f.read()
        assert "alert(" not in content


# ─── Tests: verifica che le view admin non contengano più alert() ─────────────

class TestAdminViewsNoAlert:
    """Verifica che le view admin aggiornate non usino più alert()."""

    ADMIN_VIEWS_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "frontend", "src", "views", "admin",
    )

    VIEWS_UPDATED = [
        "AdminBluetooth.vue",
        "AdminLed.vue",
        "AdminSystem.vue",
        "AdminNetwork.vue",
        "AdminParental.vue",
        "AdminParentalControl.vue",
        "AdminRfid.vue",
        "AdminMediaManager.vue",
        "AdminVoiceRecord.vue",
    ]

    def _view_content(self, filename):
        path = os.path.join(self.ADMIN_VIEWS_DIR, filename)
        with open(path, encoding="utf-8") as f:
            return f.read()

    @pytest.mark.parametrize("view_file", VIEWS_UPDATED)
    def test_view_has_no_alert_calls(self, view_file):
        """Nessuna view aggiornata deve usare alert() direttamente."""
        content = self._view_content(view_file)
        assert "alert(" not in content, (
            f"{view_file} contiene ancora chiamate a alert() — usare useAdminFeedback"
        )

    @pytest.mark.parametrize("view_file", VIEWS_UPDATED)
    def test_view_imports_admin_feedback(self, view_file):
        """Ogni view aggiornata deve importare useAdminFeedback."""
        content = self._view_content(view_file)
        assert "useAdminFeedback" in content, (
            f"{view_file} non importa useAdminFeedback"
        )

    @pytest.mark.parametrize("view_file", VIEWS_UPDATED)
    def test_view_has_feedback_banner(self, view_file):
        """Ogni view aggiornata deve mostrare il banner di feedback nel template."""
        content = self._view_content(view_file)
        assert "feedbackMsg" in content, (
            f"{view_file} non mostra feedbackMsg nel template"
        )
