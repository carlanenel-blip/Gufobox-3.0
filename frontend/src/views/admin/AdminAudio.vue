<template>
  <div class="admin-audio">

    <div class="header-section">
      <h2>Audio / HDMI 🔊</h2>
      <p>Stato dell'uscita audio, volume e configurazione HDMI.</p>
    </div>

    <!-- Loading / Error banner -->
    <div v-if="loadError" class="error-banner">
      ⚠️ {{ loadError }}
    </div>

    <!-- Audio readiness warning -->
    <div v-if="audioStatus && !audioStatus.audio_ready" class="warn-banner">
      ⚠️ <strong>Audio non pronto:</strong>
      {{ audioStatus.warning || audioStatus.note || 'Strumenti audio non trovati sul sistema.' }}
    </div>

    <!-- Status card -->
    <div class="card" v-if="audioStatus">
      <div class="card-header">
        <h3>Stato Audio</h3>
        <button class="btn-refresh" @click="loadAudioStatus" :disabled="loading">🔄</button>
      </div>

      <div class="status-grid">

        <!-- Audio ready -->
        <div class="status-item">
          <span class="status-label">Pronto</span>
          <span :class="audioStatus.audio_ready ? 'badge-ok' : 'badge-warn'">
            {{ audioStatus.audio_ready ? '✅ Sì' : '❌ No' }}
          </span>
        </div>

        <!-- Current sink -->
        <div class="status-item">
          <span class="status-label">Sink attivo</span>
          <span class="status-value mono">{{ audioStatus.current_sink || '— non determinabile' }}</span>
        </div>

        <!-- Volume -->
        <div class="status-item">
          <span class="status-label">Volume</span>
          <span class="status-value">{{ audioStatus.volume }}%</span>
        </div>

        <!-- HDMI enabled -->
        <div class="status-item">
          <span class="status-label">HDMI</span>
          <span v-if="audioStatus.hdmi_enabled === null" class="badge-gray">— N/D</span>
          <span v-else :class="audioStatus.hdmi_enabled ? 'badge-ok' : 'badge-off'">
            {{ audioStatus.hdmi_enabled ? '✅ Attivo' : '⭕ Spento' }}
          </span>
        </div>

        <!-- Auto HDMI -->
        <div class="status-item">
          <span class="status-label">Auto-HDMI</span>
          <span :class="audioStatus.auto_hdmi ? 'badge-ok' : 'badge-off'">
            {{ audioStatus.auto_hdmi ? '✅ Abilitato' : '⭕ Disabilitato' }}
          </span>
        </div>

      </div>

      <!-- Note/warning from backend -->
      <p v-if="audioStatus.note" class="note-text">ℹ️ {{ audioStatus.note }}</p>
      <p v-if="audioStatus.warning" class="warn-text">⚠️ {{ audioStatus.warning }}</p>

      <!-- Available sinks -->
      <div v-if="audioStatus.available_sinks && audioStatus.available_sinks.length > 0" class="sinks-section">
        <h4>Sink disponibili</h4>
        <ul class="sinks-list">
          <li v-for="sink in audioStatus.available_sinks" :key="sink" class="sink-item">🔊 {{ sink }}</li>
        </ul>
      </div>
      <p v-else-if="audioStatus.available_sinks !== null" class="empty-state small">
        Nessun sink rilevato (normale su sistemi senza PulseAudio / ALSA attivo).
      </p>
    </div>

    <!-- Volume control card -->
    <div class="card">
      <h3>Volume 🔉</h3>
      <div class="volume-row">
        <input
          type="range"
          min="0"
          max="100"
          v-model.number="localVolume"
          @input="onVolumeChange"
          class="volume-slider"
          :disabled="!audioStatus || !audioStatus.audio_ready"
        />
        <span class="volume-value">{{ localVolume }}%</span>
      </div>
      <p v-if="volumeMsg" :class="volumeMsgClass" class="msg-text">{{ volumeMsg }}</p>
    </div>

    <!-- HDMI control card -->
    <div class="card">
      <h3>Controllo HDMI 📺</h3>
      <p class="card-hint">
        Funziona su Raspberry Pi con <code>vcgencmd</code> disponibile.
        Su altri sistemi il comando non avrà effetto hardware ma aggiorna la preferenza.
      </p>

      <div class="hdmi-row">
        <button class="btn-hdmi on" @click="setHdmi(true)" :disabled="hdmiBusy">
          📺 Abilita HDMI
        </button>
        <button class="btn-hdmi off" @click="setHdmi(false)" :disabled="hdmiBusy">
          ⏻ Disabilita HDMI
        </button>
        <button class="btn-hdmi toggle" @click="toggleHdmi" :disabled="hdmiBusy">
          🔀 Toggle
        </button>
      </div>

      <p v-if="hdmiMsg" :class="hdmiMsgClass" class="msg-text">{{ hdmiMsg }}</p>
    </div>

    <!-- Tools card -->
    <div class="card" v-if="audioStatus">
      <h3>Strumenti audio 🛠️</h3>
      <div class="tools-grid">
        <div v-for="(available, tool) in audioStatus.tools" :key="tool" class="tool-item">
          <span :class="available ? 'badge-ok' : 'badge-off'" class="tool-badge">
            {{ available ? '✅' : '❌' }}
          </span>
          <span class="tool-name">{{ tool }}</span>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useApi } from '../../composables/useApi'

const { getApi, guardedCall, extractApiError } = useApi()

// ── stato ─────────────────────────────────────────────────────────────────────
const audioStatus = ref(null)
const loading = ref(false)
const loadError = ref(null)

const localVolume = ref(60)
const volumeMsg = ref('')
const volumeMsgType = ref('info') // 'ok' | 'warn' | 'info'
const volumeMsgClass = computed(() => ({
  'msg-ok': volumeMsgType.value === 'ok',
  'msg-warn': volumeMsgType.value === 'warn',
}))

const hdmiBusy = ref(false)
const hdmiMsg = ref('')
const hdmiMsgType = ref('info')
const hdmiMsgClass = computed(() => ({
  'msg-ok': hdmiMsgType.value === 'ok',
  'msg-warn': hdmiMsgType.value === 'warn',
}))

let volumeDebounce = null
let pollInterval = null

// ── load ───────────────────────────────────────────────────────────────────────
async function loadAudioStatus() {
  loading.value = true
  loadError.value = null
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/audio/status'))
    audioStatus.value = data
    localVolume.value = data?.volume ?? localVolume.value
  } catch (e) {
    loadError.value = extractApiError(e, 'Errore caricamento stato audio')
  } finally {
    loading.value = false
  }
}

// ── volume ─────────────────────────────────────────────────────────────────────
function onVolumeChange() {
  if (volumeDebounce) clearTimeout(volumeDebounce)
  volumeDebounce = setTimeout(applyVolume, 150)
}

async function applyVolume() {
  volumeMsg.value = ''
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.post('/audio/volume', { volume: localVolume.value }))
    localVolume.value = data?.volume ?? localVolume.value
    if (audioStatus.value) audioStatus.value.volume = localVolume.value
    volumeMsg.value = `Volume impostato a ${localVolume.value}%`
    volumeMsgType.value = 'ok'
  } catch (e) {
    volumeMsg.value = extractApiError(e, 'Errore impostazione volume')
    volumeMsgType.value = 'warn'
  }
}

// ── HDMI ───────────────────────────────────────────────────────────────────────
async function setHdmi(enabled) {
  hdmiBusy.value = true
  hdmiMsg.value = ''
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.post('/audio/hdmi', { enabled }))
    const state = data?.hdmi_enabled ? 'attivato' : 'disattivato'
    hdmiMsg.value = data?.note
      ? `HDMI ${state} — nota: ${data.note}`
      : `HDMI ${state}`
    hdmiMsgType.value = data?.applied ? 'ok' : 'warn'
    await loadAudioStatus()
  } catch (e) {
    hdmiMsg.value = extractApiError(e, 'Errore HDMI')
    hdmiMsgType.value = 'warn'
  } finally {
    hdmiBusy.value = false
  }
}

async function toggleHdmi() {
  hdmiBusy.value = true
  hdmiMsg.value = ''
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.post('/audio/hdmi', {}))
    const state = data?.hdmi_enabled ? 'attivato' : 'disattivato'
    hdmiMsg.value = data?.note
      ? `HDMI ${state} — nota: ${data.note}`
      : `HDMI ${state}`
    hdmiMsgType.value = data?.applied ? 'ok' : 'warn'
    await loadAudioStatus()
  } catch (e) {
    hdmiMsg.value = extractApiError(e, 'Errore toggle HDMI')
    hdmiMsgType.value = 'warn'
  } finally {
    hdmiBusy.value = false
  }
}

// ── lifecycle ──────────────────────────────────────────────────────────────────
onMounted(() => {
  loadAudioStatus()
  // Polling leggero ogni 30s per tenere lo stato aggiornato
  pollInterval = setInterval(loadAudioStatus, 30000)
})

onUnmounted(() => {
  clearInterval(pollInterval)
  clearTimeout(volumeDebounce)
})
</script>

<style scoped>
.admin-audio {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.header-section h2 { margin: 0; color: #fff; }
.header-section p { color: #aaa; margin: 5px 0 0 0; }

/* Banners */
.error-banner {
  background: #2a1a1a;
  border: 1px solid #e53935;
  border-radius: 10px;
  padding: 14px 18px;
  color: #ff8a80;
  font-size: 0.95rem;
}

.warn-banner {
  background: #2a2310;
  border: 1px solid #ff9800;
  border-radius: 10px;
  padding: 14px 18px;
  color: #ffcc80;
  font-size: 0.95rem;
}

/* Card */
.card {
  background: #2a2a35;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 4px 10px rgba(0,0,0,0.2);
}

.card h3 {
  margin-top: 0;
  color: #ffd27b;
  border-bottom: 1px solid #3a3a48;
  padding-bottom: 10px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #3a3a48;
  padding-bottom: 10px;
  margin-bottom: 15px;
}

.card-header h3 { border-bottom: none; padding-bottom: 0; margin: 0; }
.card-hint { color: #888; font-size: 0.85rem; margin-bottom: 15px; }

/* Status grid */
.status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}

.status-item {
  background: #1e1e26;
  border-radius: 8px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.status-label { color: #888; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.5px; }
.status-value { color: #fff; font-size: 0.95rem; font-weight: 500; }
.status-value.mono { font-family: monospace; font-size: 0.85rem; word-break: break-all; }

/* Badges */
.badge-ok  { color: #4caf50; font-weight: bold; }
.badge-off { color: #aaa; }
.badge-warn{ color: #ff9800; font-weight: bold; }
.badge-gray{ color: #666; }

/* Note / warn text */
.note-text { color: #8ab4f8; font-size: 0.85rem; margin: 5px 0 0 0; }
.warn-text { color: #ffcc80; font-size: 0.85rem; margin: 5px 0 0 0; }

/* Sinks */
.sinks-section { margin-top: 12px; }
.sinks-section h4 { color: #ccc; font-size: 0.9rem; margin: 0 0 8px 0; }
.sinks-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 5px; }
.sink-item { background: #1e1e26; border-radius: 6px; padding: 8px 12px; color: #ddd; font-size: 0.85rem; font-family: monospace; }

/* Volume */
.volume-row {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 8px;
}

.volume-slider {
  flex: 1;
  accent-color: #3f51b5;
  height: 6px;
}

.volume-value { color: #ffd27b; font-weight: bold; width: 40px; text-align: right; }

/* HDMI buttons */
.hdmi-row { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 8px; }

.btn-hdmi {
  padding: 10px 16px;
  border: none;
  border-radius: 8px;
  font-size: 0.9rem;
  cursor: pointer;
  font-weight: 600;
  transition: opacity 0.2s;
}

.btn-hdmi:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-hdmi.on     { background: #3f51b5; color: #fff; }
.btn-hdmi.off    { background: #555; color: #ccc; }
.btn-hdmi.toggle { background: #607d8b; color: #fff; }

/* Tools */
.tools-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: 8px;
  margin-top: 8px;
}

.tool-item {
  background: #1e1e26;
  border-radius: 6px;
  padding: 8px 10px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.tool-name { color: #ccc; font-size: 0.85rem; font-family: monospace; }

/* Refresh button */
.btn-refresh {
  background: transparent;
  border: 1px solid #555;
  color: #ccc;
  padding: 6px 10px;
  border-radius: 8px;
  cursor: pointer;
}

/* Messages */
.msg-text { font-size: 0.85rem; margin: 10px 0 0 0; color: #aaa; }
.msg-ok   { color: #4caf50 !important; }
.msg-warn { color: #ff9800 !important; }

/* Misc */
.empty-state { color: #666; font-style: italic; font-size: 0.85rem; }
.empty-state.small { font-size: 0.8rem; margin-top: 8px; }
</style>
