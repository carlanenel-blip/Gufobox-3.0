"""
api/rss.py — Supporto RSS completo (PR 2 — Media / RFID)

Endpoints:
  POST /api/rss/fetch    — fetch feed RSS con limit
  GET  /api/rss/current  — articoli RSS del profilo corrente
"""
import time
from urllib.parse import urlparse

from flask import Blueprint, request, jsonify

from core.state import rss_runtime, media_runtime, bus, save_json_direct
from config import RSS_RUNTIME_FILE
from core.utils import log

rss_bp = Blueprint("rss", __name__)


def _fetch_and_summarize(rss_url, limit=10):
    """
    Fetch e parse feed RSS tramite feedparser.
    Ritorna (items_list, error_string_or_None).
    items_list: lista di dict con title/link/summary/published.
    """
    try:
        import feedparser
        feed = feedparser.parse(rss_url)
        if feed.bozo and not feed.entries:
            return [], "Feed non valido o irraggiungibile"
        items = []
        for entry in feed.entries[:limit]:
            items.append({
                "title": str(entry.get("title", "")).strip(),
                "link": str(entry.get("link", "")).strip(),
                "summary": str(entry.get("summary", "")).strip()[:500],
                "published": str(entry.get("published", "")).strip(),
            })
        return items, None
    except Exception as e:
        log(f"Errore fetch RSS {rss_url}: {e}", "warning")
        return [], "Errore durante il fetch del feed RSS"


@rss_bp.route("/rss/fetch", methods=["POST"])
def api_rss_fetch():
    """
    Esegue il fetch di un feed RSS e salva il risultato nel runtime.
    Body JSON: { "rss_url": "...", "limit": 10, "rfid_code": "..." }
    """
    data = request.get_json(silent=True) or {}
    rss_url = str(data.get("rss_url", "")).strip()
    if not rss_url:
        return jsonify({"error": "rss_url è obbligatorio"}), 400
    try:
        parsed = urlparse(rss_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError
    except Exception:
        return jsonify({"error": "rss_url deve essere un URL HTTP/HTTPS valido"}), 400

    try:
        limit = max(1, min(100, int(data.get("limit", 10))))
    except (TypeError, ValueError):
        limit = 10

    rfid_code = str(data.get("rfid_code", "__manual__")).strip().upper()

    items, err = _fetch_and_summarize(rss_url, limit)
    if err:
        log(f"Errore RSS fetch: {err}", "warning")
        return jsonify({"error": "Errore durante il fetch del feed RSS"}), 500

    rss_state = {
        "rfid_code": rfid_code,
        "rss_url": rss_url,
        "fetched_at": int(time.time()),
        "items": items,
    }
    rss_runtime[rfid_code] = rss_state
    bus.mark_dirty("rss")

    # Se è il profilo corrente, aggiorna media_runtime
    if media_runtime.get("current_rfid") == rfid_code:
        media_runtime["rss_state"] = rss_state
        bus.mark_dirty("media")
        bus.request_emit("public")

    log(f"RSS fetch completato: {len(items)} articoli da {rss_url}", "info")
    return jsonify({"status": "ok", "items": items, "count": len(items)})


@rss_bp.route("/rss/current", methods=["GET"])
def api_rss_current():
    """
    Ritorna gli articoli RSS del profilo RFID corrente.
    Se rfid_code è specificato come query param, usa quello.
    """
    rfid_code = request.args.get("rfid_code", "").strip().upper()
    if not rfid_code:
        rfid_code = media_runtime.get("current_rfid", "__manual__")

    state = rss_runtime.get(rfid_code)
    if not state:
        return jsonify({"rfid_code": rfid_code, "items": [], "fetched_at": None})

    return jsonify({
        "rfid_code": rfid_code,
        "rss_url": state.get("rss_url"),
        "fetched_at": state.get("fetched_at"),
        "items": state.get("items", []),
        "count": len(state.get("items", [])),
    })
