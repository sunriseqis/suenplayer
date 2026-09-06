import { defineStore } from 'pinia'
import { ref } from 'vue'

// A1: 全局非阻塞提示条 + 确认弹窗（替代 alert / confirm）
export const useUiStore = defineStore('ui', () => {
  const toasts = ref([])
  const themeToast = ref(null)
  let _seq = 0

  function toast(message, type = 'info', duration = 3000) {
    const id = ++_seq
    toasts.value.push({ id, message, type })
    setTimeout(() => dismiss(id), duration)
    return id
  }
  function success(message, duration) { return toast(message, 'success', duration) }
  function error(message, duration = 4000) { return toast(message, 'error', duration) }
  function dismiss(id) {
    const i = toasts.value.findIndex(t => t.id === id)
    if (i >= 0) toasts.value.splice(i, 1)
  }

  // D3: 主题切换提示（复用同一条提示条通道）
  function themeChanged(name) {
    themeToast.value = { id: ++_seq, message: `已切换主题：${name}` }
    setTimeout(() => { themeToast.value = null }, 2000)
  }

  // 确认弹窗：返回 Promise<boolean>
  const confirmState = ref(null) // { message, resolve, danger }
  function confirm(message, opts = {}) {
    return new Promise((resolve) => {
      confirmState.value = { message, resolve, danger: !!opts.danger, title: opts.title || '确认操作' }
    })
  }
  function resolveConfirm(val) {
    if (!confirmState.value) return
    confirmState.value.resolve(val)
    confirmState.value = null
  }

  return { toasts, toast, success, error, dismiss, themeToast, themeChanged, confirmState, confirm, resolveConfirm }
})
