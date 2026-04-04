"""
core/jobs.py — Gestione jobs persistente.

Fornisce helpers riusabili:
  create_job(type, description, **kwargs)
  update_job(job_id, **fields)
  finish_job(job_id, status="done", message=None, error=None)
  cancel_job(job_id)
  get_job(job_id)
  list_jobs(include_old=False)
  cleanup_old_jobs(max_age_sec=86400)

Lo stato viene tenuto in RAM in core.state.jobs_state e salvato su JOB_STATE_FILE.
"""

import uuid
import time
from copy import deepcopy

from core.state import jobs_state, jobs_state_lock, bus, save_json_direct
from core.utils import log
from config import JOB_STATE_FILE

# Secondi dopo cui i job terminati vengono rimossi dal cleanup
_DEFAULT_MAX_AGE_SEC = 86400  # 24 ore


def _now():
    return int(time.time())


def _persist():
    save_json_direct(JOB_STATE_FILE, deepcopy(jobs_state))
    bus.request_emit("jobs")


def create_job(
    job_type: str,
    description: str = "",
    bytes_total: int = 0,
    items_total: int = 0,
    **extra,
) -> dict:
    """
    Crea un nuovo job, lo inserisce in jobs_state e lo persiste.
    Ritorna il dict del job creato.
    """
    job_id = str(uuid.uuid4())
    now = _now()
    job = {
        "job_id": job_id,
        "type": job_type,
        "status": "pending",
        "description": description,
        "progress_percent": 0,
        "bytes_total": bytes_total,
        "bytes_done": 0,
        "items_total": items_total,
        "items_done": 0,
        "current_item": None,
        "message": None,
        "error": None,
        "cancel_requested": False,
        "created_ts": now,
        "updated_ts": now,
        "finished_ts": None,
    }
    job.update(extra)
    with jobs_state_lock:
        jobs_state[job_id] = job
        _persist()
    log(f"Job creato: {job_id} ({job_type}) — {description}", "info")
    return deepcopy(job)


def update_job(job_id: str, **fields) -> dict | None:
    """
    Aggiorna campi di un job esistente.
    Aggiorna automaticamente updated_ts.
    Ritorna il job aggiornato o None se non trovato.
    """
    with jobs_state_lock:
        job = jobs_state.get(job_id)
        if job is None:
            log(f"update_job: job {job_id} non trovato", "warning")
            return None
        fields["updated_ts"] = _now()
        job.update(fields)
        _persist()
        return deepcopy(job)


def finish_job(
    job_id: str,
    status: str = "done",
    message: str | None = None,
    error: str | None = None,
) -> dict | None:
    """
    Segna un job come terminato (done/error/canceled).
    """
    with jobs_state_lock:
        job = jobs_state.get(job_id)
        if job is None:
            return None
        now = _now()
        job["status"] = status
        job["updated_ts"] = now
        job["finished_ts"] = now
        if message is not None:
            job["message"] = message
        if error is not None:
            job["error"] = error
        if status == "done":
            job["progress_percent"] = 100
        _persist()
    log(f"Job {job_id} terminato con status={status}", "info")
    return deepcopy(job)


def cancel_job(job_id: str) -> dict | None:
    """
    Richiede la cancellazione di un job in esecuzione.
    Imposta cancel_requested=True; il worker deve controllare questo flag.
    Se il job è già terminato, lo segna come canceled direttamente.
    """
    with jobs_state_lock:
        job = jobs_state.get(job_id)
        if job is None:
            return None
        if job["status"] in ("done", "error", "canceled"):
            return deepcopy(job)
        job["cancel_requested"] = True
        job["updated_ts"] = _now()
        # Se era in pending, cancelliamo subito
        if job["status"] == "pending":
            job["status"] = "canceled"
            job["finished_ts"] = _now()
        _persist()
    log(f"Cancellazione richiesta per job {job_id}", "info")
    return deepcopy(job)


def get_job(job_id: str) -> dict | None:
    with jobs_state_lock:
        job = jobs_state.get(job_id)
        return deepcopy(job) if job is not None else None


def list_jobs(include_old: bool = False) -> list:
    """
    Ritorna i job ordinati per created_ts desc.
    Se include_old=False esclude i job terminati da più di 24 ore.
    """
    now = _now()
    result = []
    with jobs_state_lock:
        for job in jobs_state.values():
            if not include_old:
                finished = job.get("finished_ts") or 0
                if job["status"] in ("done", "error", "canceled") and (now - finished) > _DEFAULT_MAX_AGE_SEC:
                    continue
            result.append(deepcopy(job))
    return sorted(result, key=lambda j: j.get("created_ts", 0), reverse=True)


def cleanup_old_jobs(max_age_sec: int = _DEFAULT_MAX_AGE_SEC) -> int:
    """
    Rimuove i job terminati più vecchi di max_age_sec.
    Ritorna il numero di job rimossi.
    """
    now = _now()
    with jobs_state_lock:
        to_remove = [
            jid for jid, job in jobs_state.items()
            if job["status"] in ("done", "error", "canceled")
            and (now - (job.get("finished_ts") or 0)) > max_age_sec
        ]
        for jid in to_remove:
            del jobs_state[jid]
        if to_remove:
            _persist()
            log(f"Cleanup jobs: rimossi {len(to_remove)} job vecchi", "info")
    return len(to_remove)
