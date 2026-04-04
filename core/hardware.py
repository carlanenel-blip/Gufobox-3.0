import os
import eventlet
from datetime import datetime, timedelta

from core.state import media_runtime, alarms_list, bus, now_ts
from core.utils import log, run_cmd
from hw.amp import amp_on, amp_off

# ---------------------------------------------------------------------------
# Standby state machine
# ---------------------------------------------------------------------------
# Stati espliciti del ciclo di vita standby:
#   "awake"        — sistema operativo normale
#   "standby"      — standby profondo (player off, amp off, LED off, CPU powersave)
#   "waking"       — transizione standby → awake (operazioni wake in corso)
#   "alarm_active" — sveglia scattata, audio in riproduzione
STANDBY_AWAKE = "awake"
STANDBY_STANDBY = "standby"
STANDBY_WAKING = "waking"
STANDBY_ALARM_ACTIVE = "alarm_active"

_standby_state = STANDBY_AWAKE

# Dettagli dell'ultimo/corrente standby (esposti nel public snapshot)
_standby_details = {
    "in_standby": False,
    "state": STANDBY_AWAKE,
    "wifi_blocked": False,
    "usb_suspended": False,
    "hdmi_off": False,
    "cpu_governor": None,
    "previous_governor": None,
    "entered_ts": None,
    "last_wake_reason": None,
}

# Debounce per le sveglie: ricorda (alarm_id, hour, minute) dell'ultimo scatto
# per evitare che lo stesso minuto faccia scattare più volte la stessa sveglia.
_alarm_last_fired: dict = {}

# Path USB da controllare (best-effort)
_USB_POWER_PATH = "/sys/bus/usb/devices/usb1/power/control"

# ---------------------------------------------------------------------------
# Helper: CPU governor
# ---------------------------------------------------------------------------

def _get_current_governor() -> str | None:
    """Legge il CPU governor corrente."""
    path = "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return f.read().strip()
    except Exception:
        pass
    return None


def _set_governor(governor: str) -> bool:
    """Imposta il CPU governor. Ritorna True se riuscito."""
    try:
        result = run_cmd(["sudo", "cpufreq-set", "-g", governor])
        rc = result[0] if isinstance(result, (list, tuple)) and len(result) >= 1 else 1
        if rc == 0:
            log(f"CPU governor impostato: {governor}", "info")
            return True
    except Exception:
        pass
    # Fallback: scrittura diretta
    try:
        path = "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
        if os.path.exists(path):
            with open(path, "w") as f:
                f.write(governor)
            log(f"CPU governor impostato via sysfs: {governor}", "info")
            return True
    except Exception:
        pass
    log(f"CPU governor non impostabile (hardware non presente o non privilegiato)", "debug")
    return False


# ---------------------------------------------------------------------------
# Helper: WiFi (best-effort, non blocca se è l'unica interfaccia attiva)
# ---------------------------------------------------------------------------

def _is_wifi_only_interface() -> bool:
    """Controlla se il WiFi è l'unica interfaccia con connettività."""
    try:
        result = run_cmd(["ip", "route", "get", "1.1.1.1"])
        rc = result[0] if isinstance(result, (list, tuple)) and len(result) >= 1 else 1
        out = result[1] if isinstance(result, (list, tuple)) and len(result) >= 2 else ""
        if rc != 0:
            return False
        # Se la rotta passa per un'interfaccia wireless, allora WiFi è l'unica connettività
        return "wlan" in out or "wlp" in out or "wl0" in out
    except Exception:
        return False


def _block_wifi() -> bool:
    """Blocca il WiFi se non è l'unica interfaccia attiva."""
    if _is_wifi_only_interface():
        log("WiFi è l'unica interfaccia attiva, non viene bloccato.", "info")
        return False
    try:
        result = run_cmd(["sudo", "rfkill", "block", "wifi"])
        rc = result[0] if isinstance(result, (list, tuple)) and len(result) >= 1 else 1
        if rc == 0:
            log("WiFi bloccato (rfkill).", "info")
            return True
    except Exception:
        pass
    log("rfkill block wifi: comando non disponibile o errore (best-effort).", "debug")
    return False


def _unblock_wifi():
    """Sblocca il WiFi."""
    try:
        result = run_cmd(["sudo", "rfkill", "unblock", "wifi"])
        rc = result[0] if isinstance(result, (list, tuple)) and len(result) >= 1 else 1
        if rc == 0:
            log("WiFi sbloccato (rfkill).", "info")
            return
    except Exception:
        pass
    log("rfkill unblock wifi: comando non disponibile o errore (best-effort).", "debug")


# ---------------------------------------------------------------------------
# Helper: USB suspend
# ---------------------------------------------------------------------------

def _suspend_usb() -> bool:
    """Sospende USB bus (best-effort, verifica esistenza path)."""
    if not os.path.exists(_USB_POWER_PATH):
        log(f"Path USB non trovato ({_USB_POWER_PATH}), skip USB suspend.", "debug")
        return False
    try:
        with open(_USB_POWER_PATH, "w") as f:
            f.write("suspend")
        log("USB bus sospeso.", "info")
        return True
    except Exception as e:
        log(f"USB suspend non riuscito (best-effort): {e}", "debug")
        return False


def _resume_usb():
    """Riprende USB bus."""
    if not os.path.exists(_USB_POWER_PATH):
        return
    try:
        with open(_USB_POWER_PATH, "w") as f:
            f.write("on")
        log("USB bus ripristinato.", "info")
    except Exception as e:
        log(f"USB resume non riuscito (best-effort): {e}", "debug")


def is_in_standby() -> bool:
    """Compatibilità backward: ritorna True se il sistema è in stato standby."""
    return _standby_state == STANDBY_STANDBY


def get_standby_state() -> str:
    """Ritorna lo stato standby corrente come stringa esplicita."""
    return _standby_state


def get_standby_details() -> dict:
    """Ritorna i dettagli completi dello stato standby."""
    return dict(_standby_details)


def perform_standby():
    """
    Mette la GufoBox in stato di standby a basso consumo.
    - Ferma player e amplificatore
    - Spegne LED
    - Riduce attività CPU
    - Mantiene attivo lo scheduler sveglie (il thread gira sempre)
    """
    global _standby_state, _standby_details
    from core.media import stop_player
    from hw.battery import play_ai_notification

    if _standby_state != STANDBY_AWAKE:
        log(f"perform_standby: stato corrente '{_standby_state}', non in awake — ignorato.", "warning")
        return

    bus.emit_notification("GufoBox in Standby profondo... 🌙", "warning")
    play_ai_notification("Uhuu, che sonno! Faccio un pisolino. A dopo!")
    eventlet.sleep(3)

    stop_player()
    amp_off()

    # Spegne LED
    from core.state import led_runtime
    led_runtime["master_enabled"] = False
    bus.mark_dirty("led")

    # Salva governor corrente e imposta powersave
    prev_gov = _get_current_governor()
    _set_governor("powersave")

    # Disabilita Bluetooth (best-effort)
    run_cmd(["sudo", "rfkill", "block", "bluetooth"])
    log("Bluetooth bloccato.", "info")

    # WiFi (best-effort, skip se è l'unica interfaccia)
    wifi_blocked = _block_wifi()

    # USB suspend (best-effort)
    usb_suspended = _suspend_usb()

    # Disattiva HDMI
    run_cmd(["sudo", "vcgencmd", "display_power", "0"])
    hdmi_off = True

    _standby_state = STANDBY_STANDBY
    _standby_details.update({
        "in_standby": True,
        "state": STANDBY_STANDBY,
        "wifi_blocked": wifi_blocked,
        "usb_suspended": usb_suspended,
        "hdmi_off": hdmi_off,
        "cpu_governor": "powersave",
        "previous_governor": prev_gov,
        "entered_ts": now_ts(),
        "last_wake_reason": None,
    })
    bus.request_emit("public")
    log("Standby logico attivato. Worker sveglie ancora attivo.", "info")
    try:
        from core.event_log import log_event as _lev
        _lev("standby", "info", "Standby attivato")
    except Exception:
        pass


def wake_from_standby(reason: str = "button"):
    """
    Risveglia il sistema dallo standby logico.
    Chiamato dal pulsante fisico o dallo scheduler sveglie quando scatta un allarme.
    Transizione: standby → waking → awake
    """
    global _standby_state, _standby_details

    if _standby_state not in (STANDBY_STANDBY, STANDBY_WAKING):
        log(f"wake_from_standby: stato corrente '{_standby_state}', skip.", "warning")
        return

    _standby_state = STANDBY_WAKING
    _standby_details["state"] = STANDBY_WAKING
    _standby_details["last_wake_reason"] = reason
    log(f"Wake dallo standby (motivo: {reason}): reinizializzazione hardware...", "info")

    # Ripristina HDMI
    run_cmd(["sudo", "vcgencmd", "display_power", "1"])

    # Ripristina Bluetooth
    run_cmd(["sudo", "rfkill", "unblock", "bluetooth"])

    # Ripristina WiFi se era stato bloccato
    if _standby_details.get("wifi_blocked"):
        _unblock_wifi()

    # Ripristina USB
    if _standby_details.get("usb_suspended"):
        _resume_usb()

    # Ripristina CPU governor
    prev_gov = _standby_details.get("previous_governor")
    if prev_gov:
        _set_governor(prev_gov)
    else:
        _set_governor("ondemand")

    amp_on()

    # Riabilita LED
    from core.state import led_runtime
    led_runtime["master_enabled"] = True
    bus.mark_dirty("led")

    _standby_state = STANDBY_AWAKE
    _standby_details.update({
        "in_standby": False,
        "state": STANDBY_AWAKE,
        "wifi_blocked": False,
        "usb_suspended": False,
        "hdmi_off": False,
        "cpu_governor": prev_gov or "ondemand",
    })
    bus.request_emit("public")
    log("Standby terminato — sistema sveglio.", "info")
    try:
        from core.event_log import log_event as _lev
        _lev("standby", "info", f"Wake da standby completato (motivo: {reason})")
    except Exception:
        pass
    from hw.battery import play_ai_notification
    play_ai_notification("Uhuu! Sono sveglio e pronto a giocare!")


def _wake_for_alarm():
    """
    Risveglio dedicato allo scatto di una sveglia.
    Transition: standby → waking → alarm_active
    Garantisce che amp e audio siano pronti prima della riproduzione.
    """
    global _standby_state, _standby_details

    if _standby_state == STANDBY_STANDBY:
        _standby_state = STANDBY_WAKING
        _standby_details["state"] = STANDBY_WAKING
        _standby_details["last_wake_reason"] = "alarm"
        log("Wake per sveglia: reinizializzazione hardware...", "info")

        run_cmd(["sudo", "vcgencmd", "display_power", "1"])
        run_cmd(["sudo", "rfkill", "unblock", "bluetooth"])

        if _standby_details.get("wifi_blocked"):
            _unblock_wifi()
        if _standby_details.get("usb_suspended"):
            _resume_usb()

        prev_gov = _standby_details.get("previous_governor")
        if prev_gov:
            _set_governor(prev_gov)
        else:
            _set_governor("ondemand")

        amp_on()

        from core.state import led_runtime
        led_runtime["master_enabled"] = True
        bus.mark_dirty("led")

        log("Hardware riattivato per sveglia.", "info")

    _standby_state = STANDBY_ALARM_ACTIVE
    _standby_details.update({
        "in_standby": False,
        "state": STANDBY_ALARM_ACTIVE,
    })
    bus.request_emit("public")


def _sleep_timer_worker():
    """Controlla periodicamente se il timer di spegnimento è scaduto"""
    from core.utils import is_shutdown_requested
    while not is_shutdown_requested():
        eventlet.sleep(10)
        target = media_runtime.get("sleep_timer_target_ts")
        if target and now_ts() >= target:
            log("Sleep timer scaduto! Attivazione standby.", "info")
            media_runtime["sleep_timer_target_ts"] = None
            bus.mark_dirty("media")
            bus.request_emit("public")
            perform_standby()


def _alarm_worker():
    """
    Controlla periodicamente le sveglie.
    Se è in standby, risveglia il sistema prima di riprodurre l'audio.
    Debounce: la stessa sveglia non viene eseguita più di una volta per minuto.
    """
    from core.media import start_player
    from core.utils import is_shutdown_requested

    while not is_shutdown_requested():
        eventlet.sleep(30)
        now = datetime.now()
        weekday = now.weekday()  # 0=Lun, 6=Dom
        slot = (now.hour, now.minute)  # chiave di debounce per questo minuto

        for alarm in list(alarms_list):
            if not alarm.get("enabled"):
                continue
            if alarm.get("hour") != now.hour or alarm.get("minute") != now.minute:
                continue
            days = alarm.get("days", list(range(7)))
            if weekday not in days:
                continue

            alarm_id = alarm.get("id")
            # Debounce: salta se questa sveglia è già scattata in questo minuto
            if _alarm_last_fired.get(alarm_id) == slot:
                log(f"Sveglia {alarm_id} già eseguita per {slot}, skip debounce.", "debug")
                continue
            _alarm_last_fired[alarm_id] = slot

            target = alarm.get("target", "")
            log(f"Sveglia scattata! id={alarm_id} target={target}", "info")
            try:
                from core.event_log import log_event as _lev
                _lev("standby", "info", f"Sveglia scattata (id={alarm_id})", {"alarm_id": alarm_id, "target": target})
            except Exception:
                pass

            # Risveglio hardware dedicato per la sveglia
            _wake_for_alarm()
            eventlet.sleep(2)  # Pausa anti-pop per amp

            # Voce simpatica del gufetto prima della sveglia
            try:
                from hw.battery import play_ai_notification
                play_ai_notification(
                    "Uhuuu! Sveglia sveglia amichetto! È ora di alzarsi! "
                    "Dai che oggi sarà una giornata bellissima!"
                )
                eventlet.sleep(4)  # Aspetta che finisca la voce del gufetto
            except Exception as e:
                log(f"Voce sveglia non disponibile: {e}", "warning")

            if target:
                start_player(target, mode="audio_only")

            # Dopo aver avviato il player, passa ad awake
            global _standby_state
            _standby_state = STANDBY_AWAKE
            _standby_details.update({"in_standby": False, "state": STANDBY_AWAKE})
            bus.request_emit("public")
            bus.emit_notification("⏰ Sveglia!", "info")


def _ensure_ntp_sync():
    """Forza sincronizzazione NTP all'avvio e verifica stato."""
    try:
        run_cmd(["sudo", "timedatectl", "set-ntp", "true"], timeout=5)
        code, out, _ = run_cmd(["timedatectl", "status"], timeout=5)
        if code == 0 and "synchronized: yes" in out.lower():
            log("Orologio sincronizzato via NTP ✓", "info")
        else:
            log("⚠️ Orologio NON sincronizzato (NTP non raggiungibile o disabilitato)", "warning")
    except Exception as e:
        log(f"Errore verifica NTP: {e}", "warning")


def init_hardware_workers():
    """Avvia i worker hardware in background"""
    log("Avvio worker hardware (Sleep Timer, Alarm)...", "info")
    _ensure_ntp_sync()
    eventlet.spawn(_sleep_timer_worker)
    eventlet.spawn(_alarm_worker)


