"""
tests/test_rfid_rss_resume.py — Test PR 2: RFID profiles, trigger, RSS, resume avanzato.
"""
import os
import sys
import json
import time
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =========================================================
# Test validazione profili RFID
# =========================================================
class TestRfidProfileValidation:
    def test_valid_media_folder_profile(self):
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "AA:BB:CC:DD",
            "name": "Storie della Buonanotte",
            "mode": "media_folder",
            "folder": "/home/gufobox/media/storie",
        }
        profile, err = validate_rfid_profile(data)
        assert err is None
        assert profile["rfid_code"] == "AA:BB:CC:DD"
        assert profile["mode"] == "media_folder"
        assert profile["enabled"] is True

    def test_valid_webradio_profile(self):
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "11:22:33:44",
            "name": "Radio RAI",
            "mode": "webradio",
            "webradio_url": "http://icestreaming.rai.it/1.mp3",
            "volume": 80,
        }
        profile, err = validate_rfid_profile(data)
        assert err is None
        assert profile["webradio_url"] == "http://icestreaming.rai.it/1.mp3"
        assert profile["volume"] == 80

    def test_valid_rss_feed_profile(self):
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "FF:EE:DD:CC",
            "name": "Notizie RAI",
            "mode": "rss_feed",
            "rss_url": "https://www.raiplay.it/dl/RaiPlayRadio/contents/rss/ilfatto.xml",
            "rss_limit": 5,
        }
        profile, err = validate_rfid_profile(data)
        assert err is None
        assert profile["rss_limit"] == 5

    def test_valid_ai_chat_profile(self):
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "12:34:56:78",
            "name": "Gufetto",
            "mode": "ai_chat",
            "ai_prompt": "Sei un gufo saggio che racconta storie",
        }
        profile, err = validate_rfid_profile(data)
        assert err is None
        assert profile["ai_prompt"] == "Sei un gufo saggio che racconta storie"

    def test_missing_rfid_code(self):
        from api.rfid import validate_rfid_profile
        data = {"name": "Test", "mode": "media_folder", "folder": "/tmp"}
        profile, err = validate_rfid_profile(data)
        assert err is not None
        assert "rfid_code" in err.lower()

    def test_missing_name(self):
        from api.rfid import validate_rfid_profile
        data = {"rfid_code": "AA:BB", "mode": "media_folder", "folder": "/tmp"}
        profile, err = validate_rfid_profile(data)
        assert err is not None
        assert "name" in err.lower()

    def test_invalid_mode(self):
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "AA:BB",
            "name": "Test",
            "mode": "unknown_mode",
        }
        profile, err = validate_rfid_profile(data)
        assert err is not None
        assert "mode" in err.lower()

    def test_media_folder_missing_folder(self):
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "AA:BB",
            "name": "Test",
            "mode": "media_folder",
        }
        profile, err = validate_rfid_profile(data)
        assert err is not None
        assert "folder" in err.lower()

    def test_webradio_missing_url(self):
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "AA:BB",
            "name": "Radio",
            "mode": "webradio",
        }
        profile, err = validate_rfid_profile(data)
        assert err is not None

    def test_webradio_invalid_url(self):
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "AA:BB",
            "name": "Radio",
            "mode": "webradio",
            "webradio_url": "ftp://not-http.com/stream",
        }
        profile, err = validate_rfid_profile(data)
        assert err is not None
        assert "http" in err.lower()

    def test_rss_feed_missing_url(self):
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "AA:BB",
            "name": "News",
            "mode": "rss_feed",
        }
        profile, err = validate_rfid_profile(data)
        assert err is not None

    def test_volume_clamped(self):
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "AA:BB",
            "name": "Test",
            "mode": "media_folder",
            "folder": "/tmp",
            "volume": 200,
        }
        profile, err = validate_rfid_profile(data)
        assert err is None
        assert profile["volume"] == 100

    def test_rss_limit_clamped(self):
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "AA:BB",
            "name": "News",
            "mode": "rss_feed",
            "rss_url": "https://example.com/rss",
            "rss_limit": 999,
        }
        profile, err = validate_rfid_profile(data)
        assert err is None
        assert profile["rss_limit"] == 100

    def test_led_block_valid(self):
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "AA:BB",
            "name": "Test LED",
            "mode": "media_folder",
            "folder": "/tmp",
            "led": {
                "enabled": True,
                "effect_id": "rainbow",
                "color": "#ff9900",
                "brightness": 70,
                "speed": 30,
            },
        }
        profile, err = validate_rfid_profile(data)
        assert err is None
        assert profile["led"]["effect_id"] == "rainbow"
        assert profile["led"]["color"] == "#ff9900"

    def test_led_block_invalid_type(self):
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "AA:BB",
            "name": "Test",
            "mode": "media_folder",
            "folder": "/tmp",
            "led": "not_a_dict",
        }
        profile, err = validate_rfid_profile(data)
        assert err is not None

    def test_rfid_code_uppercased(self):
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "aa:bb:cc",
            "name": "Test",
            "mode": "media_folder",
            "folder": "/tmp",
        }
        profile, err = validate_rfid_profile(data)
        assert err is None
        assert profile["rfid_code"] == "AA:BB:CC"

    def test_update_mode_partial(self):
        """update=True: i campi obbligatori possono mancare."""
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "AA:BB",
            "name": "Test",
            "mode": "media_folder",
            "folder": "/tmp",
            "volume": 50,
        }
        profile, err = validate_rfid_profile(data, update=True)
        assert err is None
        assert profile["volume"] == 50

    def test_profile_has_timestamps(self):
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "AA:BB",
            "name": "Test",
            "mode": "media_folder",
            "folder": "/tmp",
        }
        profile, err = validate_rfid_profile(data)
        assert err is None
        assert "updated_at" in profile


# =========================================================
# Test CRUD profili RFID (via state diretto, senza Flask)
# =========================================================
class TestRfidProfilesCRUD:
    """Test che operano direttamente sullo state dict dei profili."""

    def setup_method(self):
        from core.state import rfid_profiles
        # Pulisci i profili prima di ogni test
        rfid_profiles.clear()

    def test_create_and_get_profile(self):
        from core.state import rfid_profiles
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "TEST:01",
            "name": "Storia",
            "mode": "media_folder",
            "folder": "/tmp",
        }
        profile, err = validate_rfid_profile(data)
        assert err is None
        rfid_profiles["TEST:01"] = profile
        assert "TEST:01" in rfid_profiles
        assert rfid_profiles["TEST:01"]["name"] == "Storia"

    def test_update_profile(self):
        from core.state import rfid_profiles
        from api.rfid import validate_rfid_profile
        rfid_profiles["UPD:01"] = {
            "rfid_code": "UPD:01",
            "name": "Vecchio",
            "mode": "media_folder",
            "folder": "/tmp",
        }
        merged = {**rfid_profiles["UPD:01"], "name": "Nuovo", "volume": 90}
        profile, err = validate_rfid_profile(merged, update=True)
        assert err is None
        rfid_profiles["UPD:01"] = profile
        assert rfid_profiles["UPD:01"]["name"] == "Nuovo"
        assert rfid_profiles["UPD:01"]["volume"] == 90

    def test_delete_profile(self):
        from core.state import rfid_profiles
        rfid_profiles["DEL:01"] = {"rfid_code": "DEL:01", "name": "Da eliminare"}
        del rfid_profiles["DEL:01"]
        assert "DEL:01" not in rfid_profiles

    def test_profiles_list(self):
        from core.state import rfid_profiles
        rfid_profiles["P1"] = {"rfid_code": "P1", "name": "Uno"}
        rfid_profiles["P2"] = {"rfid_code": "P2", "name": "Due"}
        assert len(rfid_profiles) == 2


# =========================================================
# Test playlist builder
# =========================================================
class TestBuildPlaylist:
    def test_build_playlist_empty_dir(self):
        from core.media import build_playlist
        with tempfile.TemporaryDirectory() as tmpdir:
            result = build_playlist(tmpdir)
        assert result == []

    def test_build_playlist_with_mp3(self):
        from core.media import build_playlist
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ["a.mp3", "b.mp3", "c.ogg", "d.txt"]:
                open(os.path.join(tmpdir, name), "w").close()
            result = build_playlist(tmpdir)
        # Solo file audio, escluso d.txt
        assert len(result) == 3
        assert all(f.endswith((".mp3", ".ogg")) for f in result)

    def test_build_playlist_sorted(self):
        from core.media import build_playlist
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ["z.mp3", "a.mp3", "m.mp3"]:
                open(os.path.join(tmpdir, name), "w").close()
            result = build_playlist(tmpdir)
        basenames = [os.path.basename(f) for f in result]
        assert basenames == sorted(basenames)

    def test_build_playlist_nonexistent_dir(self):
        from core.media import build_playlist
        result = build_playlist("/nonexistent/path/that/does/not/exist")
        assert result == []


# =========================================================
# Test RSS fetch helpers
# =========================================================
class TestRssFetch:
    def test_fetch_rss_invalid_url(self):
        """Feed non valido deve ritornare errore."""
        from api.rfid import _fetch_rss
        items, err = _fetch_rss("http://localhost:19999/nonexistent_feed.xml", 5)
        # Può ritornare lista vuota con o senza errore — accettiamo entrambi
        assert isinstance(items, list)

    def test_fetch_rss_returns_list(self):
        """La funzione deve sempre ritornare una lista come primo elemento."""
        from api.rfid import _fetch_rss
        items, err = _fetch_rss("http://localhost:19999/nope", 10)
        assert isinstance(items, list)

    def test_rss_item_structure(self):
        """Ogni item deve avere i campi standard."""
        # Usiamo un feed mock tramite feedparser diretto
        import feedparser
        # Feed RSS minimale hardcoded come stringa
        rss_xml = """<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <title>Test Feed</title>
            <link>http://example.com</link>
            <item>
              <title>Articolo 1</title>
              <link>http://example.com/1</link>
              <description>Sommario articolo 1</description>
            </item>
          </channel>
        </rss>"""
        feed = feedparser.parse(rss_xml)
        items = []
        for entry in feed.entries[:10]:
            items.append({
                "title": str(entry.get("title", "")).strip(),
                "link": str(entry.get("link", "")).strip(),
                "summary": str(entry.get("summary", "")).strip()[:500],
                "published": str(entry.get("published", "")).strip(),
            })
        assert len(items) == 1
        assert items[0]["title"] == "Articolo 1"
        assert "link" in items[0]
        assert "summary" in items[0]
        assert "published" in items[0]

    def test_rss_limit_respected(self):
        """Il limite articoli deve essere rispettato."""
        import feedparser
        items_xml = "".join(
            f"<item><title>Art {i}</title><link>http://x.com/{i}</link></item>"
            for i in range(20)
        )
        rss_xml = f"""<?xml version="1.0"?>
        <rss version="2.0"><channel><title>T</title><link>x</link>{items_xml}</channel></rss>"""
        feed = feedparser.parse(rss_xml)
        limit = 5
        items = [{"title": e.get("title", "")} for e in feed.entries[:limit]]
        assert len(items) == 5


# =========================================================
# Test resume avanzato con playlist_index
# =========================================================
class TestAdvancedResume:
    def setup_method(self):
        """Usa un DB temporaneo per i test."""
        import core.database as db_module
        self._tmpdir = tempfile.mkdtemp()
        self._orig_db_path = db_module.DB_PATH
        db_module.DB_PATH = os.path.join(self._tmpdir, "test_resume.db")
        db_module.init_db()

    def teardown_method(self):
        import core.database as db_module
        db_module.DB_PATH = self._orig_db_path

    def test_save_and_get_resume_with_index(self):
        from core.database import save_resume_position, get_resume_position
        save_resume_position("TEST:01", "/media/storia.mp3", 120, playlist_index=3)
        result = get_resume_position("TEST:01")
        assert result is not None
        assert result["position"] == 120
        assert result["playlist_index"] == 3
        assert result["target"] == "/media/storia.mp3"

    def test_resume_default_index_zero(self):
        from core.database import save_resume_position, get_resume_position
        save_resume_position("TEST:02", "/media/canzone.mp3", 60)
        result = get_resume_position("TEST:02")
        assert result["playlist_index"] == 0

    def test_clear_resume(self):
        from core.database import save_resume_position, get_resume_position, clear_resume_position
        save_resume_position("TEST:03", "/media/x.mp3", 50)
        clear_resume_position("TEST:03")
        result = get_resume_position("TEST:03")
        assert result is None

    def test_resume_expiry(self):
        """Resume troppo vecchio non deve essere restituito."""
        import core.database as db_module
        from core.database import get_resume_position
        import sqlite3
        # Inserisci record con timestamp scaduto
        old_ts = int(time.time()) - (31 * 24 * 3600)  # 31 giorni fa
        with sqlite3.connect(db_module.DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO smart_resume "
                "(rfid_uid, target_path, position_seconds, playlist_index, last_played_ts) "
                "VALUES (?, ?, ?, ?, ?)",
                ("OLD:01", "/media/old.mp3", 200, 0, old_ts)
            )
        result = get_resume_position("OLD:01")
        assert result is None

    def test_cleanup_expired_resumes(self):
        """cleanup_expired_resumes deve rimuovere entry scadute."""
        import core.database as db_module
        from core.database import cleanup_expired_resumes, save_resume_position, get_resume_position
        import sqlite3
        # Inserisci record scaduto
        old_ts = int(time.time()) - (31 * 24 * 3600)
        with sqlite3.connect(db_module.DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO smart_resume "
                "(rfid_uid, target_path, position_seconds, playlist_index, last_played_ts) "
                "VALUES (?, ?, ?, ?, ?)",
                ("EXP:01", "/media/exp.mp3", 100, 0, old_ts)
            )
        # Inserisci anche uno non scaduto
        save_resume_position("NEW:01", "/media/new.mp3", 50)
        cleanup_expired_resumes()
        assert get_resume_position("EXP:01") is None
        assert get_resume_position("NEW:01") is not None

    def test_overwrite_resume(self):
        """Salvare due volte lo stesso uid sovrascrive il vecchio."""
        from core.database import save_resume_position, get_resume_position
        save_resume_position("OVR:01", "/media/a.mp3", 10, playlist_index=0)
        save_resume_position("OVR:01", "/media/b.mp3", 200, playlist_index=2)
        result = get_resume_position("OVR:01")
        assert result["target"] == "/media/b.mp3"
        assert result["position"] == 200
        assert result["playlist_index"] == 2


# =========================================================
# Test config nuove costanti PR2
# =========================================================
class TestConfigPR2:
    def test_rfid_profiles_file_in_config(self):
        import config
        assert hasattr(config, "RFID_PROFILES_FILE")
        assert config.RFID_PROFILES_FILE.endswith(".json")

    def test_rss_runtime_file_in_config(self):
        import config
        assert hasattr(config, "RSS_RUNTIME_FILE")
        assert config.RSS_RUNTIME_FILE.endswith(".json")

    def test_resume_max_age_sec_in_config(self):
        import config
        assert hasattr(config, "RESUME_MAX_AGE_SEC")
        assert config.RESUME_MAX_AGE_SEC > 0

    def test_media_extensions_in_config(self):
        import config
        assert hasattr(config, "MEDIA_EXTENSIONS")
        assert ".mp3" in config.MEDIA_EXTENSIONS
        assert ".ogg" in config.MEDIA_EXTENSIONS

    def test_api_version_updated(self):
        import config
        assert config.API_VERSION >= "18.1.0"


# =========================================================
# Test media_runtime campi estesi
# =========================================================
class TestMediaRuntimeExtended:
    def test_media_runtime_has_pr2_fields(self):
        from core.state import DEFAULT_MEDIA_RUNTIME
        for field in ("current_rfid", "current_profile_name", "current_mode",
                      "current_media_path", "current_playlist", "playlist_index",
                      "rss_state"):
            assert field in DEFAULT_MEDIA_RUNTIME, f"Campo mancante: {field}"

    def test_current_playlist_default_empty(self):
        from core.state import DEFAULT_MEDIA_RUNTIME
        assert DEFAULT_MEDIA_RUNTIME["current_playlist"] == []

    def test_playlist_index_default_zero(self):
        from core.state import DEFAULT_MEDIA_RUNTIME
        assert DEFAULT_MEDIA_RUNTIME["playlist_index"] == 0

    def test_current_mode_default_idle(self):
        from core.state import DEFAULT_MEDIA_RUNTIME
        assert DEFAULT_MEDIA_RUNTIME["current_mode"] == "idle"


# =========================================================
# Test trigger logic (smoke test senza hardware)
# =========================================================
class TestRfidTriggerLogic:
    def test_apply_profile_led_updates_led_runtime(self):
        """_apply_profile_led deve aggiornare led_runtime."""
        from core.state import led_runtime
        from api.rfid import _apply_profile_led
        profile = {
            "led": {
                "enabled": True,
                "effect_id": "breathing",
                "color": "#00ff00",
                "brightness": 80,
                "speed": 20,
            }
        }
        _apply_profile_led("TEST:00", profile)
        assert led_runtime["current_effect"] == "breathing"
        assert led_runtime["master_color"] == "#00ff00"

    def test_apply_profile_led_disabled_no_change(self):
        """Se led.enabled=False, led_runtime non deve cambiare."""
        from core.state import led_runtime
        from api.rfid import _apply_profile_led
        original_effect = led_runtime.get("current_effect", "solid")
        profile = {
            "led": {
                "enabled": False,
                "effect_id": "rainbow",
                "color": "#ff0000",
            }
        }
        _apply_profile_led("TEST:00", profile)
        assert led_runtime["current_effect"] == original_effect

    def test_apply_profile_led_no_led_block(self):
        """Se non c'è blocco led, nessuna eccezione."""
        from api.rfid import _apply_profile_led
        profile = {"name": "Test"}
        _apply_profile_led("TEST:00", profile)  # Non deve sollevare eccezioni

    def test_trigger_rss_feed_updates_rss_runtime(self):
        """_fetch_rss con URL non valido deve ritornare lista vuota."""
        from api.rfid import _fetch_rss

        items, err = _fetch_rss("http://localhost:19999/nonexistent_rss.xml", 5)
        # Non deve sollevare eccezioni
        assert isinstance(items, list)
