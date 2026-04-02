"""
api/audio.py — Endpoints audio/HDMI per GufoBox.

  GET  /audio/status  — stato audio: sink, volume, HDMI, readiness (best-effort)
  POST /audio/volume  — imposta il volume (0-100)
  POST /audio/hdmi    — abilita / disabilita HDMI auto (toggle o set esplicito)
"""

import re
import shutil

from flask import Blueprint, request, jsonify

from core.state import media_runtime, state
from core.utils import log, run_cmd

audio_bp = Blueprint("audio", __name__)

# Pattern per sanitizzare i nomi dei sink (solo caratteri safe per output admin)
_SAFE_NAME_RE = re.compile(r"[^\w\s\-_.:,()]+")
_MAX_NAME_LEN = 120


def _sanitize_name(raw: str) -> str:
    """Rimuove caratteri non-safe da un nome di sink prima di esporlo al frontend."""
    return _SAFE_NAME_RE.sub("", raw).strip()[:_MAX_NAME_LEN]


# ─── helpers ─────────────────────────────────────────────────────────────────

def _tool(name: str) -> bool:
    """Verifica se uno strumento di sistema è disponibile (shutil.which)."""
    return shutil.which(name) is not None


def _get_current_sink() -> str | None:
    """
    Tenta di leggere il default-sink ALSA/PulseAudio in modo best-effort.
    Ritorna una stringa descrittiva sanitizzata oppure None.
    """
    # 1. Prova pactl (PulseAudio / PipeWire)
    if _tool("pactl"):
        try:
            code, out, _ = run_cmd(["pactl", "info"], timeout=3)
            if code == 0:
                for line in out.splitlines():
                    if "Default Sink:" in line:
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            return _sanitize_name(parts[1])
        except Exception:
            pass

    # 2. Prova amixer per leggere il card/control name (ALSA)
    if _tool("amixer"):
        try:
            code, out, _ = run_cmd(["amixer", "info"], timeout=3)
            if code == 0:
                for line in out.splitlines():
                    if "Card:" in line or "Device:" in line:
                        return _sanitize_name(line)
        except Exception:
            pass

    return None


def _get_available_sinks() -> list[str]:
    """
    Tenta di elencare i sink audio disponibili in modo best-effort.
    Ritorna una lista (può essere vuota) di nomi sanitizzati.
    """
    if _tool("pactl"):
        try:
            code, out, _ = run_cmd(["pactl", "list", "short", "sinks"], timeout=3)
            if code == 0 and out.strip():
                return [
                    _sanitize_name(line.split("\t")[1])
                    for line in out.splitlines()
                    if "\t" in line
                ]
        except Exception:
            pass

    if _tool("aplay"):
        try:
            code, out, _ = run_cmd(["aplay", "-l"], timeout=3)
            if code == 0 and out.strip():
                sinks = []
                for line in out.splitlines():
                    if line.startswith("card "):
                        sinks.append(_sanitize_name(line))
                return sinks
        except Exception:
            pass

    return []


def _get_hdmi_enabled() -> bool | None:
    """
    Tenta di rilevare se l'uscita HDMI è attiva usando vcgencmd (solo RPi).
    Ritorna True/False oppure None se lo strumento non è disponibile.
    """
    if not _tool("vcgencmd"):
        return None
    try:
        code, out, _ = run_cmd(["vcgencmd", "display_power"], timeout=3)
        if code == 0:
            return "display_power=1" in out
    except Exception:
        pass
    return None


def _get_auto_hdmi() -> bool:
    """
    Legge la preferenza auto-HDMI dallo stato persistente.
    Default: True (HDMI abilitato automaticamente all'avvio).
    """
    return bool(state.get("audio_config", {}).get("auto_hdmi", True))


def _get_volume() -> int:
    """Legge il volume corrente dal runtime (già gestito da /volume di media.py)."""
    return int(media_runtime.get("current_volume", 60))


def _build_audio_status() -> dict:
    """
    Costruisce il payload dello stato audio in modo best-effort.
    Non crasha mai — i campi non determinabili vengono esposti come None.
    """
    has_mpv = _tool("mpv")
    has_amixer = _tool("amixer")
    has_aplay = _tool("aplay")
    has_pactl = _tool("pactl")

    audio_ready = has_mpv  # mpv è il player principale
    current_sink = _get_current_sink()
    available_sinks = _get_available_sinks()
    volume = _get_volume()
    hdmi_enabled = _get_hdmi_enabled()
    auto_hdmi = _get_auto_hdmi()

    # Determina la nota/warning più rilevante
    note = None
    warning = None
    if not has_mpv:
        warning = "mpv non trovato: la riproduzione audio non funzionerà"
    elif not has_amixer and not has_pactl:
        note = "amixer/pactl non trovati: il controllo volume potrebbe non funzionare"

    return {
        "audio_ready": audio_ready,
        "current_sink": current_sink,
        "available_sinks": available_sinks,
        "volume": volume,
        "hdmi_enabled": hdmi_enabled,
        "auto_hdmi": auto_hdmi,
        "tools": {
            "mpv": has_mpv,
            "amixer": has_amixer,
            "aplay": has_aplay,
            "pactl": has_pactl,
            "vcgencmd": _tool("vcgencmd"),
        },
        "note": note,
        "warning": warning,
    }


# ─── endpoints ───────────────────────────────────────────────────────────────

@audio_bp.route("/audio/status", methods=["GET"])
def api_audio_status():
    """
    Restituisce lo stato audio completo in modo best-effort.
    Utile per il pannello admin per capire lo stato reale dell'audio.
    """
    return jsonify(_build_audio_status())


@audio_bp.route("/audio/volume", methods=["POST"])
def api_audio_set_volume():
    """
    Imposta il volume master (0-100).
    Alias più esplicito di /volume — entrambi gli endpoint rimangono disponibili.
    Payload: {"volume": <int 0-100>}
    """
    data = request.get_json(silent=True) or {}
    new_vol = data.get("volume")

    if new_vol is None:
        return jsonify({"error": "Campo 'volume' mancante"}), 400

    try:
        new_vol = max(0, min(100, int(new_vol)))
    except (TypeError, ValueError):
        return jsonify({"error": "Valore volume non valido (atteso intero 0-100)"}), 400

    # Rispetta il Parental Control se configurato
    max_allowed = state.get("parental_control", {}).get("max_volume", 100)
    if new_vol > max_allowed:
        new_vol = max_allowed

    # Applica via amixer (ALSA) — best-effort
    if _tool("amixer"):
        code, _, err = run_cmd(["amixer", "sset", "Master", f"{new_vol}%"])
        if code != 0:
            log(f"amixer sset fallito (non critico): {err}", "warning")

    media_runtime["current_volume"] = new_vol

    from core.state import bus
    bus.mark_dirty("media")
    bus.request_emit("public")

    return jsonify({"status": "ok", "volume": new_vol})


@audio_bp.route("/audio/hdmi", methods=["POST"])
def api_audio_hdmi_toggle():
    """
    Abilita / disabilita HDMI (su RPi usa vcgencmd display_power).
    Aggiorna anche la preferenza auto_hdmi nello stato persistente.

    Payload opzionale: {"enabled": true|false}
    Se non specificato, fa un toggle rispetto allo stato corrente.
    """
    data = request.get_json(silent=True) or {}

    # Determina il valore desiderato
    if "enabled" in data:
        try:
            enabled = bool(data["enabled"])
        except (TypeError, ValueError):
            return jsonify({"error": "Campo 'enabled' non valido (atteso bool)"}), 400
    else:
        # Toggle: se HDMI era attivo → spegnilo, altrimenti accendilo
        current = _get_hdmi_enabled()
        enabled = not current if current is not None else True

    # Applica via vcgencmd (solo RPi)
    applied = False
    note = None
    if _tool("vcgencmd"):
        power_val = "1" if enabled else "0"
        code, _out, _err = run_cmd(["vcgencmd", "display_power", power_val], timeout=3)
        if code == 0:
            applied = True
            log(f"HDMI display_power={power_val} applicato", "info")
        else:
            note = "vcgencmd display_power fallito: impossibile modificare lo stato HDMI"
            log(f"vcgencmd fallito (non critico): {_err}", "warning")
    else:
        note = "vcgencmd non disponibile: HDMI non controllabile via software su questo sistema"

    # Salva la preferenza auto_hdmi nello stato persistente
    if "audio_config" not in state:
        state["audio_config"] = {}
    state["audio_config"]["auto_hdmi"] = enabled

    return jsonify({
        "status": "ok",
        "hdmi_enabled": enabled,
        "applied": applied,
        "note": note,
    })
