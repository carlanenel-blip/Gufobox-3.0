import os
import hashlib
from flask import Blueprint, request, jsonify, send_file

# Importiamo la configurazione e lo stato
from config import AI_SETTINGS_FILE, AI_TTS_CACHE_DIR, OPENAI_API_KEY
from core.state import ai_runtime, led_runtime, bus, load_json, save_json_direct
from core.utils import log
from core.event_log import log_event

# Proviamo a importare OpenAI (se installato)
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

ai_bp = Blueprint('ai', __name__)

# Carichiamo le impostazioni dell'AI (System prompt, voce, ecc.)
ai_settings = load_json(AI_SETTINGS_FILE, {
    "system_prompt": "Sei il Gufetto Magico, un assistente amichevole e saggio che parla ai bambini.",
    "temperature": 0.7,
    "tts_provider": "browser",
    "openai_api_key": OPENAI_API_KEY
})

# Canonical AI status values
AI_STATUS_IDLE = "idle"
AI_STATUS_LISTENING = "listening"
AI_STATUS_THINKING = "thinking"
AI_STATUS_SPEAKING = "speaking"
AI_STATUS_ERROR = "error"


def _set_ai_state(status: str, error: str = None):
    """
    Update the canonical AI status in ai_runtime and sync to LED runtime.

    status: "idle" | "listening" | "thinking" | "speaking" | "error"
    error:  optional error message (set when status == "error")
    """
    ai_runtime["status"] = status
    # Keep legacy boolean fields in sync for backward compat
    ai_runtime["is_thinking"] = status == AI_STATUS_THINKING
    ai_runtime["is_speaking"] = status == AI_STATUS_SPEAKING
    if status == AI_STATUS_ERROR and error:
        ai_runtime["last_error"] = error
    elif status == AI_STATUS_IDLE:
        ai_runtime["last_error"] = None
    # Sync to LED layer (None when idle so LED reverts to default)
    led_ai = status if status != AI_STATUS_IDLE else None
    try:
        from api.led import refresh_effective_led
        led_runtime["ai_state"] = led_ai
        refresh_effective_led()
    except Exception as e:
        log(f"Errore aggiornamento LED per stato AI '{status}': {e}", "warning")
    bus.mark_dirty("ai")
    bus.request_emit("public")


def get_openai_client():
    """Inizializza il client OpenAI usando la chiave salvata nelle impostazioni"""
    api_key = ai_settings.get("openai_api_key") or OPENAI_API_KEY
    if not api_key or not OpenAI:
        return None
    return OpenAI(api_key=api_key)

# =========================================================
# IMPOSTAZIONI AI (Per il pannello Admin)
# =========================================================
@ai_bp.route("/ai/settings", methods=["GET"])
def api_ai_settings_get():
    # Nascondiamo in parte la chiave API per sicurezza quando la inviamo al frontend
    safe_settings = ai_settings.copy()
    key = safe_settings.get("openai_api_key", "")
    if len(key) > 8:
        safe_settings["openai_api_key"] = key[:4] + "*" * (len(key)-8) + key[-4:]
    return jsonify(safe_settings)

@ai_bp.route("/ai/settings", methods=["POST"])
def api_ai_settings_post():
    data = request.get_json(silent=True) or {}
    
    # Aggiorniamo solo i campi inviati (se la chiave API contiene '*', significa che non è stata modificata)
    for k, v in data.items():
        if k == "openai_api_key" and "*" in str(v):
            continue
        ai_settings[k] = v
        
    save_json_direct(AI_SETTINGS_FILE, ai_settings)
    log("Impostazioni AI aggiornate", "info")
    return jsonify({"status": "ok"})

# =========================================================
# STATUS AI
# =========================================================
@ai_bp.route("/ai/status", methods=["GET"])
def api_ai_status():
    """Return the current AI runtime status."""
    return jsonify({
        "status": ai_runtime.get("status", AI_STATUS_IDLE),
        "last_error": ai_runtime.get("last_error"),
        "history_length": len(ai_runtime.get("history", [])),
        "tts_provider": ai_settings.get("tts_provider", "browser"),
        "openai_configured": bool(ai_settings.get("openai_api_key") or OPENAI_API_KEY),
    })

# =========================================================
# CHAT E CONVERSAZIONE
# =========================================================
@ai_bp.route("/ai/chat", methods=["POST"])
def api_ai_chat():
    data = request.get_json(silent=True) or {}
    user_text = data.get("text", "").strip()
    
    if not user_text:
        return jsonify({"error": "Testo vuoto"}), 400

    client = get_openai_client()
    if not client:
        msg = "OpenAI non configurato. Inserisci la API Key nelle impostazioni."
        log_event("ai", "error", "AI chat fallita: OpenAI non configurato")
        return jsonify({"error": msg, "code": "openai_not_configured"}), 503

    # 1. Aggiungiamo il messaggio dell'utente alla storia con timestamp
    import time as _time
    ai_runtime["history"].append({
        "role": "user",
        "content": user_text,
        "ts": int(_time.time()),
    })
    
    # Manteniamo solo gli ultimi 10 messaggi per non consumare troppi token
    if len(ai_runtime["history"]) > 10:
        ai_runtime["history"] = ai_runtime["history"][-10:]

    # Segnaliamo al frontend che il gufetto sta pensando...
    _set_ai_state(AI_STATUS_THINKING)

    try:
        # 2. Prepariamo i messaggi per OpenAI
        messages = [{"role": "system", "content": ai_settings.get("system_prompt", "")}]
        # OpenAI expects only role/content fields
        for h in ai_runtime["history"]:
            messages.append({"role": h["role"], "content": h["content"]})

        # 3. Chiamata alle API di OpenAI
        response = client.chat.completions.create(
            model=ai_settings.get("model", "gpt-3.5-turbo"),
            messages=messages,
            temperature=float(ai_settings.get("temperature", 0.7)),
            max_tokens=300
        )
        
        ai_reply = response.choices[0].message.content.strip()

        # 4. Salviamo la risposta nella storia con timestamp
        ai_runtime["history"].append({
            "role": "assistant",
            "content": ai_reply,
            "ts": int(_time.time()),
        })
        # Trim again to keep the cap at 10 (including the just-added reply)
        if len(ai_runtime["history"]) > 10:
            ai_runtime["history"] = ai_runtime["history"][-10:]
        
        # 5. Generiamo l'audio se il TTS provider è OpenAI
        audio_url = None
        if ai_settings.get("tts_provider") == "openai":
            # Creiamo un hash del testo per la cache (così non paghiamo due volte per la stessa frase)
            text_hash = hashlib.md5(ai_reply.encode('utf-8')).hexdigest()
            audio_path = os.path.join(AI_TTS_CACHE_DIR, f"{text_hash}.mp3")
            
            if not os.path.exists(audio_path):
                tts_response = client.audio.speech.create(
                    model="tts-1",
                    voice="nova", # Voce adatta ai bambini
                    input=ai_reply
                )
                tts_response.stream_to_file(audio_path)
                
            audio_url = f"/api/ai/tts/{text_hash}.mp3"

    except Exception as e:
        err_msg = str(e)
        log(f"Errore OpenAI: {err_msg}", "error")
        log_event("ai", "error", "Errore risposta OpenAI", {"error": err_msg[:200]})
        _set_ai_state(AI_STATUS_ERROR, error=err_msg)
        return jsonify({"error": "Errore del provider AI. Riprova tra poco."}), 500

    # Fine elaborazione: speaking se c'è audio OpenAI, altrimenti idle
    next_state = AI_STATUS_SPEAKING if audio_url else AI_STATUS_IDLE
    _set_ai_state(next_state)

    return jsonify({
        "status": "ok",
        "reply": ai_reply,
        "audio_url": audio_url
    })

# =========================================================
# STOP AI
# =========================================================
@ai_bp.route("/ai/stop", methods=["POST"])
def api_ai_stop():
    """Stop current AI activity and reset to idle."""
    _set_ai_state(AI_STATUS_IDLE)
    return jsonify({"status": "ok"})

# =========================================================
# LISTENING STATE (per STT browser)
# =========================================================
@ai_bp.route("/ai/listen/start", methods=["POST"])
def api_ai_listen_start():
    """Signal that the browser STT is starting (updates state to listening)."""
    _set_ai_state(AI_STATUS_LISTENING)
    return jsonify({"status": "ok"})

@ai_bp.route("/ai/listen/stop", methods=["POST"])
def api_ai_listen_stop():
    """Signal that browser STT has stopped (revert to idle if still listening)."""
    if ai_runtime.get("status") == AI_STATUS_LISTENING:
        _set_ai_state(AI_STATUS_IDLE)
    return jsonify({"status": "ok"})

# =========================================================
# PULIZIA STORIA E LETTURA AUDIO TTS
# =========================================================
@ai_bp.route("/ai/clear-history", methods=["POST"])
@ai_bp.route("/ai/clear", methods=["POST"])
def api_ai_clear_history():
    """Clear chat history and reset state. Accessible at both /ai/clear-history and /ai/clear."""
    try:
        ai_runtime["history"] = []
        _set_ai_state(AI_STATUS_IDLE)
        bus.emit_notification("Memoria del Gufetto cancellata 🧹", "info")
        return jsonify({"status": "ok"})
    except Exception as e:
        log_event("ai", "error", "Reset chat fallito", {"error": str(e)})
        return jsonify({"error": "Reset chat fallito"}), 500

@ai_bp.route("/ai/tts/<filename>", methods=["GET"])
def api_ai_tts_serve(filename):
    """Serve il file audio generato da OpenAI"""
    safe_name = os.path.basename(filename)
    file_path = os.path.join(AI_TTS_CACHE_DIR, safe_name)
    if os.path.exists(file_path):
        return send_file(file_path, mimetype="audio/mpeg")
    return jsonify({"error": "File non trovato"}), 404

def ai_age_profile_rules(age_profile):
    """Regole di comunicazione basate sull'età"""
    profiles = {
        "bambino": {
            "style": "Usa frasi cortissime e semplici. Parla come a un bambino di 4 anni. Usa tanti emoji e onomatopee (Uhuu! Wow!). Non usare parole difficili."
        },
        "ragazzo": {
            "style": "Puoi usare frasi un po' più articolate. Fai battute simpatiche. Spiega le cose in modo curioso e coinvolgente."
        },
        "adulto": {
            "style": "Parla in modo chiaro e amichevole. Puoi essere più dettagliato nelle spiegazioni."
        }
    }
    return profiles.get(age_profile, profiles["bambino"])

def ai_system_prompt(age_profile, interactive_mode="chat_normale", target_lang="it"):
    rules = ai_age_profile_rules(age_profile)
    
    base = f"""Sei un piccolo gufetto magico, dolce e simpatico.
Il tuo compito principale è intrattenere, educare e rassicurare.
L'utente ha un'età stimata: {age_profile}.
{rules['style']}
"""
    # Gestione Modalità Interattive (#14)
    if interactive_mode == "quiz_animali":
        base += "\nMODALITÀ GIOCO: Fai il verso di un animale scrivendolo (es. 'Miao!') e chiedi al bambino di indovinare quale animale è. Attendi la risposta e fai i complimenti!"
    elif interactive_mode == "storia_interattiva":
        base += "\nMODALITÀ STORIA: Inizia a raccontare una storia, poi fermati e fai scegliere al bambino tra due opzioni su come farla proseguire."
    elif interactive_mode == "insegnante_lingue":
        base += f"\nMODALITÀ LINGUA: Devi insegnare qualche parola in {target_lang}. Dì una parola semplice in italiano, poi dilla in {target_lang} e chiedi al bambino di ripeterla."
    
    base += "\n\nEvita contenuti spaventosi. Sii brevissimo (max 2-3 frasi)."
    return base

@ai_bp.route("/ai/play_game", methods=["POST"])
def api_ai_start_game():
    data = request.get_json(silent=True) or {}
    game_type = data.get("game_type", "quiz_animali") # quiz_animali, storia_interattiva, insegnante_lingue
    lang = data.get("lang", "en") # en, es, de
    
    # Inizializza la conversazione con il prompt del gioco
    prompt = ai_system_prompt(ai_settings.get("age_profile", "bambino"), game_type, lang)
    # L'implementazione completa invierà questo prompt come primo messaggio al motore OpenAI...
    
    return jsonify({"status": "ok", "game_started": game_type})

