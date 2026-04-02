import sqlite3
import os
import time
from datetime import datetime
from config import DATA_DIR, RESUME_MAX_AGE_SEC
from core.utils import log

DB_PATH = os.path.join(DATA_DIR, "gufobox.db")

def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Inizializza le tabelle del database se non esistono"""
    try:
        with _get_conn() as conn:
            # Tabella per le statistiche di ascolto (#11)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS listening_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT,
                    rfid_uid TEXT,
                    duration_seconds INTEGER
                )
            ''')
            # Tabella per il Resume Intelligente degli Audiolibri (#8) — versione avanzata
            conn.execute('''
                CREATE TABLE IF NOT EXISTS smart_resume (
                    rfid_uid TEXT PRIMARY KEY,
                    target_path TEXT,
                    position_seconds INTEGER,
                    playlist_index INTEGER DEFAULT 0,
                    last_played_ts INTEGER
                )
            ''')
            # Aggiunge la colonna playlist_index se non esiste (migrazione da versione precedente)
            try:
                conn.execute("ALTER TABLE smart_resume ADD COLUMN playlist_index INTEGER DEFAULT 0")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise
        log("Database SQLite (Statistiche e Resume) inizializzato.", "info")
    except Exception as e:
        log(f"Errore inizializzazione DB: {e}", "error")

# --- FUNZIONI STATISTICHE (#11) ---
def log_listening_session(rfid_uid, duration_seconds):
    """Salva una sessione di ascolto conclusa"""
    if duration_seconds < 10: return # Ignora ascolti troppo brevi
    
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO listening_stats (date, rfid_uid, duration_seconds) VALUES (?, ?, ?)",
                (today, rfid_uid, duration_seconds)
            )
    except Exception as e:
        log(f"Errore salvataggio stat: {e}", "warning")

def get_daily_stats():
    """Recupera i minuti totali ascoltati per ogni giorno (per il grafico frontend)"""
    try:
        with _get_conn() as conn:
            cursor = conn.execute('''
                SELECT date, SUM(duration_seconds) as total_sec 
                FROM listening_stats 
                GROUP BY date 
                ORDER BY date DESC LIMIT 7
            ''')
            return [{"date": row["date"], "minutes": round(row["total_sec"]/60)} for row in cursor]
    except Exception as e:
        log(f"Errore nel recupero statistiche settimanali: {e}", "warning")
        return []

# --- FUNZIONI SMART RESUME (#8) — avanzato ---
def save_resume_position(rfid_uid, target_path, position_sec, playlist_index=0):
    """Salva a che punto è arrivato il bambino in una storia (incluso indice playlist)"""
    try:
        with _get_conn() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO smart_resume
                    (rfid_uid, target_path, position_seconds, playlist_index, last_played_ts)
                VALUES (?, ?, ?, ?, ?)
            ''', (rfid_uid, target_path, position_sec, playlist_index, int(time.time())))
    except Exception as e:
        log(f"Errore salvataggio resume: {e}", "warning")

def clear_resume_position(rfid_uid):
    """
    Azzera la posizione di resume per una statuina quando il file è finito naturalmente.
    Evita di ripartire dalla fine alla prossima riproduzione.
    """
    try:
        with _get_conn() as conn:
            conn.execute("DELETE FROM smart_resume WHERE rfid_uid = ?", (rfid_uid,))
    except Exception as e:
        log(f"Errore cancellazione resume: {e}", "warning")

def get_resume_position(rfid_uid):
    """Recupera il secondo esatto da cui ripartire per una specifica statuina"""
    try:
        cutoff = int(time.time()) - RESUME_MAX_AGE_SEC
        with _get_conn() as conn:
            cursor = conn.execute(
                "SELECT target_path, position_seconds, playlist_index, last_played_ts "
                "FROM smart_resume WHERE rfid_uid = ? AND last_played_ts > ?",
                (rfid_uid, cutoff)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "target": row["target_path"],
                    "position": row["position_seconds"],
                    "playlist_index": row["playlist_index"] or 0,
                    "last_played_ts": row["last_played_ts"],
                }
    except Exception as e:
        log(f"Errore nel recupero posizione smart resume: {e}", "warning")
    return None

def cleanup_expired_resumes():
    """Rimuove i resume scaduti (più vecchi di RESUME_MAX_AGE_SEC)"""
    try:
        cutoff = int(time.time()) - RESUME_MAX_AGE_SEC
        with _get_conn() as conn:
            conn.execute("DELETE FROM smart_resume WHERE last_played_ts < ?", (cutoff,))
        log("Resume scaduti rimossi dal database.", "info")
    except Exception as e:
        log(f"Errore pulizia resume scaduti: {e}", "warning")

