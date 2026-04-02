<template>
  <div class="admin-dashboard">

    <div class="dashboard-header">
      <h2>Dashboard 📊</h2>
      <button class="btn-refresh" @click="refreshAll" :disabled="loading">
        {{ loading ? '🔄 Aggiornamento...' : '🔄 Aggiorna' }}
      </button>
    </div>

    <!-- Offline banner -->
    <div v-if="offline" class="offline-banner">
      ⚠️ Backend non raggiungibile — modalità offline. Alcuni dati potrebbero non essere aggiornati.
    </div>

    <!-- Loading state -->
    <div v-if="loading && !metrics && !summary" class="loading-banner">
      ⏳ Caricamento dati in corso...
    </div>

    <!-- Standby banner -->
    <div v-if="summary && summary.in_standby" class="standby-banner">
      🌙 <strong>GufoBox in standby</strong>
    </div>

    <!-- Hardware metrics grid -->
    <div class="stats-grid" v-if="metrics">

      <div class="stat-card">
        <div class="stat-icon">🌡️</div>
        <div class="stat-details">
          <h3>CPU</h3>
          <p class="stat-value">
            {{ metrics.cpu_temp_celsius != null ? metrics.cpu_temp_celsius + '°C' : 'N/D' }}
          </p>
          <p class="stat-sub" v-if="metrics.cpu_load">
            Load: {{ metrics.cpu_load.load_1 ?? 'N/D' }}
          </p>
        </div>
      </div>

      <div class="stat-card">
        <div class="stat-icon">🧠</div>
        <div class="stat-details">
          <h3>RAM</h3>
          <p class="stat-value">
            {{ metrics.ram?.used_mb ?? '—' }} / {{ metrics.ram?.total_mb ?? '—' }} MB
          </p>
          <div class="mini-progress" v-if="metrics.ram?.percent != null">
            <div class="mini-progress-fill" :style="{ width: metrics.ram.percent + '%' }"></div>
          </div>
        </div>
      </div>

      <div class="stat-card">
        <div class="stat-icon">💾</div>
        <div class="stat-details">
          <h3>Disco</h3>
          <p class="stat-value">
            {{ metrics.disk?.used_gb ?? '—' }} / {{ metrics.disk?.total_gb ?? '—' }} GB
          </p>
          <div class="mini-progress" v-if="metrics.disk?.percent != null">
            <div class="mini-progress-fill disk-fill" :style="{ width: metrics.disk.percent + '%' }"></div>
          </div>
        </div>
      </div>

      <div class="stat-card">
        <div class="stat-icon">⏱️</div>
        <div class="stat-details">
          <h3>Uptime</h3>
          <p class="stat-value">{{ formatUptime(metrics.uptime_seconds) }}</p>
          <p class="stat-sub" v-if="metrics.battery">
            🔋 {{ metrics.battery.percent ?? '—' }}%
          </p>
        </div>
      </div>

    </div>

    <div v-else-if="!loading" class="empty-state">
      Metriche hardware non disponibili — il backend potrebbe essere in avvio o non raggiungibile.
    </div>

    <!-- Status overview from diag/summary -->
    <div class="status-grid" v-if="summary">

      <div class="status-item" :class="summary.player_running ? 'status-ok' : 'status-idle'">
        <span class="status-icon">🎵</span>
        <div>
          <p class="status-label">Media</p>
          <p class="status-val">{{ summary.player_running ? summary.player_mode || 'In riproduzione' : 'Fermo' }}</p>
        </div>
      </div>

      <div class="status-item" :class="socketConnected ? 'status-ok' : 'status-error'">
        <span class="status-icon">🔗</span>
        <div>
          <p class="status-label">Connessione</p>
          <p class="status-val">{{ socketConnected ? 'Online' : 'Offline' }}</p>
        </div>
      </div>

      <div class="status-item" :class="summary.ota_running ? 'status-warn' : 'status-idle'">
        <span class="status-icon">⬆️</span>
        <div>
          <p class="status-label">OTA</p>
          <p class="status-val">{{ summary.ota_running ? 'In corso...' : summary.ota_status || 'idle' }}</p>
        </div>
      </div>

      <div class="status-item" :class="summary.active_jobs > 0 ? 'status-warn' : 'status-idle'">
        <span class="status-icon">⚙️</span>
        <div>
          <p class="status-label">Job attivi</p>
          <p class="status-val">{{ summary.active_jobs ?? 0 }}</p>
        </div>
      </div>

      <div class="status-item" :class="summary.ok ? 'status-ok' : 'status-warn'">
        <span class="status-icon">{{ summary.ok ? '✅' : '⚠️' }}</span>
        <div>
          <p class="status-label">Sistema</p>
          <p class="status-val">{{ summary.ok ? 'OK' : (summary.warnings?.[0] || 'Avvisi presenti') }}</p>
        </div>
      </div>

      <div class="status-item status-idle">
        <span class="status-icon">💾</span>
        <div>
          <p class="status-label">Backup</p>
          <p class="status-val">{{ summary.backup_count ?? '—' }} disponibili</p>
        </div>
      </div>

    </div>

    <!-- Warnings box -->
    <div v-if="summary && summary.warnings && summary.warnings.length > 0" class="warnings-box">
      <h4>⚠️ Avvisi</h4>
      <ul>
        <li v-for="w in summary.warnings" :key="w">{{ w }}</li>
      </ul>
    </div>

  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useApi } from '../../composables/useApi'

const { guardedCall, getApi, extractApiError, offline, socketConnected } = useApi()

const metrics = ref(null)
const summary = ref(null)
const loading = ref(false)
let pollingTimer = null

async function fetchMetrics() {
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/admin/metrics'))
    metrics.value = data
  } catch (e) {
    console.warn('Metriche non disponibili:', extractApiError(e))
  }
}

async function fetchSummary() {
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/diag/summary'))
    summary.value = data
  } catch (e) {
    console.warn('Summary non disponibile:', extractApiError(e))
  }
}

async function refreshAll() {
  loading.value = true
  await Promise.all([fetchMetrics(), fetchSummary()])
  loading.value = false
}

function formatUptime(seconds) {
  if (!seconds) return '0h 0m'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return `${h}h ${m}m`
}

onMounted(() => {
  refreshAll()
  pollingTimer = setInterval(refreshAll, 15000)
})

onBeforeUnmount(() => {
  if (pollingTimer) clearInterval(pollingTimer)
})
</script>

<style scoped>
.admin-dashboard {
  display: flex;
  flex-direction: column;
  gap: 25px;
}

.dashboard-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #3a3a48;
  padding-bottom: 15px;
}

.dashboard-header h2 { margin: 0; color: #fff; }

.btn-refresh {
  background: #3a3a48;
  color: white;
  border: none;
  padding: 8px 15px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-refresh:hover:not(:disabled) { background: #4a4a5a; }
.btn-refresh:disabled { opacity: 0.6; cursor: not-allowed; }

/* Offline / standby banners */
.offline-banner {
  background: #2a1a1a;
  border: 1px solid #ff4d4d;
  border-radius: 10px;
  padding: 12px 18px;
  color: #ff8a80;
  font-size: 0.95rem;
}

.standby-banner {
  background: #1e2a4a;
  border: 1px solid #3f51b5;
  border-radius: 10px;
  padding: 12px 18px;
  color: #8ab4f8;
  font-size: 0.95rem;
}

.loading-banner {
  background: #1e1e26;
  border: 1px solid #3a3a48;
  border-radius: 10px;
  padding: 12px 18px;
  color: #aaa;
  font-size: 0.95rem;
}

/* Hardware metrics */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
}

.stat-card {
  background: #2a2a35;
  border-radius: 12px;
  padding: 18px;
  display: flex;
  align-items: center;
  gap: 14px;
  box-shadow: 0 4px 10px rgba(0,0,0,0.2);
}

.stat-card .stat-icon {
  font-size: 2rem;
  width: 52px;
  height: 52px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #1e1e26;
  border-radius: 10px;
  flex-shrink: 0;
}

.stat-details h3 { margin: 0 0 4px 0; font-size: 0.85rem; color: #aaa; text-transform: uppercase; letter-spacing: 0.5px; }
.stat-value { margin: 0; font-size: 1.25rem; font-weight: bold; color: #fff; }
.stat-sub { margin: 4px 0 0 0; font-size: 0.8rem; color: #ffd27b; }

.mini-progress {
  width: 100%;
  height: 5px;
  background: #1e1e26;
  border-radius: 3px;
  margin-top: 8px;
  overflow: hidden;
}

.mini-progress-fill { height: 100%; background: #4caf50; transition: width 0.5s ease; }
.disk-fill { background: #3f51b5; }

/* Status overview */
.status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
}

.status-item {
  display: flex;
  align-items: center;
  gap: 12px;
  background: #2a2a35;
  border-radius: 10px;
  padding: 14px;
  border-left: 4px solid #555;
}

.status-ok { border-left-color: #4caf50; }
.status-warn { border-left-color: #ff9800; }
.status-error { border-left-color: #ff4d4d; }
.status-idle { border-left-color: #555; }

.status-icon { font-size: 1.5rem; flex-shrink: 0; }
.status-label { margin: 0; font-size: 0.75rem; color: #aaa; text-transform: uppercase; }
.status-val { margin: 2px 0 0 0; font-size: 0.95rem; font-weight: bold; color: #fff; }

/* Warnings */
.warnings-box {
  background: #2a1e14;
  border: 1px solid #ff9800;
  border-radius: 10px;
  padding: 16px 20px;
  color: #ffd27b;
}

.warnings-box h4 { margin: 0 0 10px 0; }
.warnings-box ul { margin: 0; padding-left: 20px; }
.warnings-box li { margin-bottom: 4px; font-size: 0.9rem; }

.empty-state {
  text-align: center;
  padding: 30px;
  color: #aaa;
  background: #2a2a35;
  border-radius: 12px;
  font-style: italic;
}
</style>

