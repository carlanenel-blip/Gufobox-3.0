"""
tests/test_audio_hdmi_pr7.py — PR 7: Audio/HDMI hardening + frontend/backend edge-case alignment.

Covers:
A) Audio status endpoint
   - GET /audio/status returns 200 with expected shape
   - audio_ready=False when mpv is missing (fallback without tools)
   - warning field populated when mpv missing
   - current_sink, available_sinks, volume, hdmi_enabled, auto_hdmi, tools keys present

B) Audio volume endpoint
   - POST /audio/volume returns 200 and correct volume
   - rejects missing volume field
   - rejects non-numeric volume
   - clamps volume to 0-100

C) Audio HDMI endpoint
   - POST /audio/hdmi with enabled=True/False returns 200
   - POST /audio/hdmi without vcgencmd sets applied=False and returns note
   - POST /audio/hdmi (toggle) without body is accepted
   - applied=True when vcgencmd present and succeeds

D) Diag summary audio fields
   - GET /diag/summary includes audio_ready field
   - GET /diag/summary includes audio_note field
   - GET /diag/summary readiness.audio has expected sub-keys

E) Health endpoint
   - GET /health returns 200 (frontend selectApiBase uses /health not /ping)

F) Volume route alignment
   - GET /volume returns 200 (backend endpoint used by useMedia.js)
   - POST /volume with valid payload returns 200
"""

import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def audio_app():
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.audio import audio_bp

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-audio-secret"
    flask_app.config["TESTING"] = True
    CORS(flask_app)
    flask_app.register_blueprint(audio_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")
    return flask_app


@pytest.fixture()
def audio_client(audio_app):
    with audio_app.test_client() as c:
        yield c


@pytest.fixture()
def diag_app():
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.diag import diag_bp

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-diag-secret"
    flask_app.config["TESTING"] = True
    CORS(flask_app)
    flask_app.register_blueprint(diag_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")
    return flask_app


@pytest.fixture()
def diag_client(diag_app):
    with diag_app.test_client() as c:
        yield c


@pytest.fixture()
def full_app():
    """App con tutti i blueprint necessari per i test di integrazione."""
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.system import system_bp
    from api.media import media_bp
    from api.audio import audio_bp

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-full-secret"
    flask_app.config["TESTING"] = True
    CORS(flask_app)
    flask_app.register_blueprint(system_bp, url_prefix="/api")
    flask_app.register_blueprint(media_bp, url_prefix="/api")
    flask_app.register_blueprint(audio_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")
    return flask_app


@pytest.fixture()
def full_client(full_app):
    with full_app.test_client() as c:
        yield c


# ─── A) Audio status endpoint ─────────────────────────────────────────────────

class TestAudioStatus:

    def test_status_returns_200(self, audio_client):
        """GET /audio/status deve ritornare 200."""
        rv = audio_client.get("/api/audio/status")
        assert rv.status_code == 200

    def test_status_has_required_keys(self, audio_client):
        """Il payload deve includere tutti i campi richiesti dal pannello admin."""
        rv = audio_client.get("/api/audio/status")
        data = rv.get_json()
        assert data is not None
        for key in ("audio_ready", "current_sink", "available_sinks", "volume",
                    "hdmi_enabled", "auto_hdmi", "tools", "note", "warning"):
            assert key in data, f"Campo mancante: {key}"

    def test_status_tools_subkeys(self, audio_client):
        """Il sotto-dizionario tools deve avere i campi strumenti principali."""
        rv = audio_client.get("/api/audio/status")
        data = rv.get_json()
        tools = data.get("tools", {})
        for tool in ("mpv", "amixer", "aplay", "vcgencmd"):
            assert tool in tools, f"Tool mancante: {tool}"

    def test_status_audio_not_ready_without_mpv(self, audio_client):
        """Se mpv non è disponibile, audio_ready deve essere False."""
        with patch("api.audio._tool", return_value=False):
            rv = audio_client.get("/api/audio/status")
            data = rv.get_json()
            assert data["audio_ready"] is False

    def test_status_warning_populated_without_mpv(self, audio_client):
        """Se mpv non è disponibile, il campo warning deve essere non-None."""
        with patch("api.audio._tool", return_value=False):
            rv = audio_client.get("/api/audio/status")
            data = rv.get_json()
            assert data["warning"] is not None
            assert "mpv" in data["warning"].lower()

    def test_status_audio_ready_with_mpv(self, audio_client):
        """Se mpv è disponibile, audio_ready deve essere True."""
        def mock_tool(name):
            return name == "mpv"
        with patch("api.audio._tool", side_effect=mock_tool):
            rv = audio_client.get("/api/audio/status")
            data = rv.get_json()
            assert data["audio_ready"] is True

    def test_status_volume_is_integer(self, audio_client):
        """Il campo volume deve essere un intero."""
        rv = audio_client.get("/api/audio/status")
        data = rv.get_json()
        assert isinstance(data["volume"], int)

    def test_status_available_sinks_is_list(self, audio_client):
        """available_sinks deve essere una lista (anche vuota)."""
        rv = audio_client.get("/api/audio/status")
        data = rv.get_json()
        assert isinstance(data["available_sinks"], list)

    def test_status_hdmi_none_without_vcgencmd(self, audio_client):
        """Se vcgencmd non è disponibile, hdmi_enabled deve essere None."""
        with patch("api.audio._tool", return_value=False):
            rv = audio_client.get("/api/audio/status")
            data = rv.get_json()
            assert data["hdmi_enabled"] is None

    def test_status_no_crash_when_commands_fail(self, audio_client):
        """Anche se i comandi di sistema falliscono, /audio/status non deve crashare."""
        with patch("api.audio.run_cmd", side_effect=Exception("cmd failed")):
            rv = audio_client.get("/api/audio/status")
            assert rv.status_code == 200


# ─── B) Audio volume endpoint ─────────────────────────────────────────────────

class TestAudioVolume:

    def test_set_volume_ok(self, audio_client):
        """POST /audio/volume con payload valido deve restituire 200 e il volume corretto."""
        with patch("api.audio.run_cmd", return_value=(0, "", "")), \
             patch("api.audio._tool", return_value=True):
            rv = audio_client.post("/api/audio/volume",
                                   json={"volume": 75},
                                   content_type="application/json")
            assert rv.status_code == 200
            data = rv.get_json()
            assert data["status"] == "ok"
            assert data["volume"] == 75

    def test_set_volume_missing_field(self, audio_client):
        """POST /audio/volume senza il campo volume deve restituire 400."""
        rv = audio_client.post("/api/audio/volume",
                               json={},
                               content_type="application/json")
        assert rv.status_code == 400

    def test_set_volume_invalid_type(self, audio_client):
        """POST /audio/volume con valore non numerico deve restituire 400."""
        rv = audio_client.post("/api/audio/volume",
                               json={"volume": "alto"},
                               content_type="application/json")
        assert rv.status_code == 400

    def test_set_volume_clamps_max(self, audio_client):
        """Il volume viene clampato a 100 se il valore supera il massimo (senza parental control)."""
        from core.state import state
        # Rimuovi temporaneamente il parental control per testare il clamping a 100
        orig = state.pop("parental_control", None)
        try:
            with patch("api.audio.run_cmd", return_value=(0, "", "")), \
                 patch("api.audio._tool", return_value=True):
                rv = audio_client.post("/api/audio/volume",
                                       json={"volume": 150},
                                       content_type="application/json")
                assert rv.status_code == 200
                assert rv.get_json()["volume"] == 100
        finally:
            if orig is not None:
                state["parental_control"] = orig

    def test_set_volume_clamps_min(self, audio_client):
        """Il volume viene clampato a 0 se il valore è negativo."""
        with patch("api.audio.run_cmd", return_value=(0, "", "")), \
             patch("api.audio._tool", return_value=True):
            rv = audio_client.post("/api/audio/volume",
                                   json={"volume": -10},
                                   content_type="application/json")
            assert rv.status_code == 200
            assert rv.get_json()["volume"] == 0

    def test_set_volume_without_amixer_ok(self, audio_client):
        """Se amixer non è disponibile, il volume viene comunque impostato in RAM senza crash."""
        with patch("api.audio._tool", return_value=False):
            rv = audio_client.post("/api/audio/volume",
                                   json={"volume": 50},
                                   content_type="application/json")
            assert rv.status_code == 200
            assert rv.get_json()["volume"] == 50


# ─── C) Audio HDMI endpoint ───────────────────────────────────────────────────

class TestAudioHdmi:

    def test_hdmi_enable_returns_200(self, audio_client):
        """POST /audio/hdmi con enabled=true deve ritornare 200."""
        with patch("api.audio._tool", return_value=False):
            rv = audio_client.post("/api/audio/hdmi",
                                   json={"enabled": True},
                                   content_type="application/json")
            assert rv.status_code == 200

    def test_hdmi_disable_returns_200(self, audio_client):
        """POST /audio/hdmi con enabled=false deve ritornare 200."""
        with patch("api.audio._tool", return_value=False):
            rv = audio_client.post("/api/audio/hdmi",
                                   json={"enabled": False},
                                   content_type="application/json")
            assert rv.status_code == 200

    def test_hdmi_toggle_empty_body_returns_200(self, audio_client):
        """POST /audio/hdmi senza body deve essere accettato (toggle)."""
        with patch("api.audio._tool", return_value=False):
            rv = audio_client.post("/api/audio/hdmi",
                                   json={},
                                   content_type="application/json")
            assert rv.status_code == 200

    def test_hdmi_without_vcgencmd_applied_false(self, audio_client):
        """Senza vcgencmd, applied deve essere False e note deve indicarlo."""
        with patch("api.audio._tool", return_value=False):
            rv = audio_client.post("/api/audio/hdmi",
                                   json={"enabled": True},
                                   content_type="application/json")
            data = rv.get_json()
            assert data["applied"] is False
            assert data["note"] is not None
            assert "vcgencmd" in data["note"]

    def test_hdmi_with_vcgencmd_applied_true(self, audio_client):
        """Con vcgencmd disponibile e comando riuscito, applied deve essere True."""
        def mock_tool(name):
            return name == "vcgencmd"

        with patch("api.audio._tool", side_effect=mock_tool), \
             patch("api.audio.run_cmd", return_value=(0, "display_power=1", "")):
            rv = audio_client.post("/api/audio/hdmi",
                                   json={"enabled": True},
                                   content_type="application/json")
            data = rv.get_json()
            assert data["applied"] is True
            assert data["note"] is None

    def test_hdmi_payload_has_hdmi_enabled_field(self, audio_client):
        """Il payload di risposta deve sempre includere il campo hdmi_enabled."""
        with patch("api.audio._tool", return_value=False):
            rv = audio_client.post("/api/audio/hdmi", json={"enabled": True})
            data = rv.get_json()
            assert "hdmi_enabled" in data

    def test_hdmi_updates_auto_hdmi_state(self, audio_client):
        """Il toggle HDMI deve aggiornare la preferenza auto_hdmi nello stato."""
        from core.state import state
        state.pop("audio_config", None)
        with patch("api.audio._tool", return_value=False):
            audio_client.post("/api/audio/hdmi", json={"enabled": True})
        assert state.get("audio_config", {}).get("auto_hdmi") is True


# ─── D) Diag summary audio fields ─────────────────────────────────────────────

class TestDiagSummaryAudioFields:

    def test_diag_summary_has_audio_ready(self, diag_client):
        """GET /diag/summary deve includere il campo audio_ready."""
        rv = diag_client.get("/api/diag/summary")
        data = rv.get_json()
        assert "audio_ready" in data, "Campo audio_ready mancante in /diag/summary"

    def test_diag_summary_has_audio_note(self, diag_client):
        """GET /diag/summary deve includere il campo audio_note."""
        rv = diag_client.get("/api/diag/summary")
        data = rv.get_json()
        assert "audio_note" in data, "Campo audio_note mancante in /diag/summary"

    def test_diag_summary_readiness_audio_sub_keys(self, diag_client):
        """readiness.audio deve avere i sotto-campi ok/mpv/amixer/aplay/note."""
        rv = diag_client.get("/api/diag/summary")
        data = rv.get_json()
        audio_r = data.get("readiness", {}).get("audio", {})
        for k in ("ok", "mpv", "amixer", "aplay", "note"):
            assert k in audio_r, f"Sub-campo readiness.audio.{k} mancante"

    def test_diag_summary_audio_ready_is_bool(self, diag_client):
        """audio_ready deve essere un booleano."""
        rv = diag_client.get("/api/diag/summary")
        data = rv.get_json()
        assert isinstance(data["audio_ready"], bool)


# ─── E) Health endpoint ───────────────────────────────────────────────────────

class TestHealthEndpoint:

    @pytest.fixture()
    def system_app(self):
        from flask import Flask
        from flask_cors import CORS
        from core.extensions import socketio
        from api.system import system_bp

        flask_app = Flask(__name__)
        flask_app.secret_key = "test-system-secret"
        flask_app.config["TESTING"] = True
        CORS(flask_app)
        flask_app.register_blueprint(system_bp, url_prefix="/api")
        socketio.init_app(flask_app, async_mode="threading")
        return flask_app

    @pytest.fixture()
    def system_client(self, system_app):
        with system_app.test_client() as c:
            yield c

    def test_health_endpoint_exists(self, system_client):
        """/api/health deve restituire 200 (usato da useApi.selectApiBase)."""
        rv = system_client.get("/api/health")
        assert rv.status_code == 200

    def test_health_payload_ok(self, system_client):
        """/api/health deve restituire {"status": "ok"}."""
        rv = system_client.get("/api/health")
        data = rv.get_json()
        assert data.get("status") == "ok"

    def test_ping_still_works(self, system_client):
        """/api/ping deve continuare a funzionare per retrocompatibilità."""
        rv = system_client.get("/api/ping")
        assert rv.status_code == 200


# ─── F) Volume route alignment ────────────────────────────────────────────────

class TestVolumeRouteAlignment:

    def test_get_volume_returns_200(self, full_client):
        """GET /volume deve restituire 200 (rotta usata da useMedia.js)."""
        rv = full_client.get("/api/volume")
        assert rv.status_code == 200

    def test_get_volume_has_volume_field(self, full_client):
        """GET /volume deve restituire il campo volume."""
        rv = full_client.get("/api/volume")
        data = rv.get_json()
        assert "volume" in data
        assert isinstance(data["volume"], (int, float))

    def test_post_volume_ok(self, full_client):
        """POST /volume con payload valido deve restituire 200."""
        with patch("api.media.run_cmd", return_value=(0, "", "")):
            rv = full_client.post("/api/volume",
                                  json={"volume": 55},
                                  content_type="application/json")
            assert rv.status_code == 200
            data = rv.get_json()
            assert data.get("volume") == 55

    def test_post_audio_volume_also_works(self, full_client):
        """POST /audio/volume (endpoint audio.py) deve restituire 200."""
        with patch("api.audio.run_cmd", return_value=(0, "", "")), \
             patch("api.audio._tool", return_value=True):
            rv = full_client.post("/api/audio/volume",
                                  json={"volume": 40},
                                  content_type="application/json")
            assert rv.status_code == 200
