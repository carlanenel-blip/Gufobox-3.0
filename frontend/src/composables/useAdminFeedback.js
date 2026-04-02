import { ref } from 'vue'

/**
 * useAdminFeedback — composable condiviso per feedback inline nelle sezioni admin.
 *
 * Uso tipico nel template:
 *   <AdminFeedbackBanner :msg="feedbackMsg" :type="feedbackType" @close="clearFeedback" />
 *
 * Oppure direttamente con le classi banner dell'admin:
 *   <div v-if="feedbackMsg" class="banner" :class="'banner-' + feedbackType">
 *     <span>{{ feedbackMsg }}</span>
 *     <button class="banner-close" @click="clearFeedback">✕</button>
 *   </div>
 *
 * Ogni chiamata a useAdminFeedback() crea uno stato locale al componente chiamante.
 */
export function useAdminFeedback(autoHideMs = 4000) {
  const feedbackMsg = ref(null)
  const feedbackType = ref('info') // 'success' | 'error' | 'warning' | 'info'

  let _timer = null

  function _schedule(ms) {
    if (_timer) clearTimeout(_timer)
    if (ms > 0) {
      _timer = setTimeout(() => { feedbackMsg.value = null }, ms)
    }
  }

  /** Mostra un messaggio di successo (scompare automaticamente). */
  function showSuccess(msg, ms = autoHideMs) {
    feedbackType.value = 'success'
    feedbackMsg.value = msg
    _schedule(ms)
  }

  /** Mostra un messaggio di errore (rimane finché non chiuso manualmente). */
  function showError(msg) {
    feedbackType.value = 'error'
    feedbackMsg.value = msg
    _schedule(0) // non auto-hide
  }

  /** Mostra un avviso (rimane finché non chiuso manualmente). */
  function showWarning(msg) {
    feedbackType.value = 'warning'
    feedbackMsg.value = msg
    _schedule(0)
  }

  /** Mostra un messaggio informativo (scompare automaticamente). */
  function showInfo(msg, ms = autoHideMs) {
    feedbackType.value = 'info'
    feedbackMsg.value = msg
    _schedule(ms)
  }

  /** Nasconde il messaggio corrente. */
  function clearFeedback() {
    if (_timer) clearTimeout(_timer)
    feedbackMsg.value = null
  }

  return {
    feedbackMsg,
    feedbackType,
    showSuccess,
    showError,
    showWarning,
    showInfo,
    clearFeedback,
  }
}
