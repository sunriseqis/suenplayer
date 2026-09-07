<template>
  <Teleport to="body">
    <!-- A1: 底部非阻塞提示条 -->
    <div class="toast-stack" aria-live="polite">
      <div v-for="t in ui.toasts" :key="t.id" class="toast-bar" :class="'toast-' + t.type" @click="ui.dismiss(t.id)">
        <svg v-if="t.type === 'success'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
        <svg v-else-if="t.type === 'error'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
        <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="16"/><line x1="12" y1="7.5" x2="12.01" y2="7.5"/></svg>
        <span class="toast-msg">{{ t.message }}</span>
        <button class="toast-close" @click.stop="ui.dismiss(t.id)">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><line x1="5" y1="5" x2="19" y2="19"/><line x1="19" y1="5" x2="5" y2="19"/></svg>
        </button>
      </div>
      <div v-if="ui.themeToast" :key="'theme-' + ui.themeToast.id" class="toast-bar toast-theme">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
        <span class="toast-msg">{{ ui.themeToast.message }}</span>
      </div>
    </div>

    <!-- A1: 确认弹窗（替代原生 confirm） -->
    <div v-if="ui.confirmState" class="confirm-overlay" @click.self="ui.resolveConfirm(false)">
      <div class="confirm-panel">
        <div class="confirm-title">{{ ui.confirmState.title }}</div>
        <div class="confirm-msg">{{ ui.confirmState.message }}</div>
        <div class="confirm-actions">
          <template v-if="ui.confirmState.actions && ui.confirmState.actions.length">
            <button v-for="a in ui.confirmState.actions" :key="a.label"
                    class="btn" :class="a.danger ? 'btn-danger' : (a.kind || 'btn-secondary')"
                    style="flex:1;height:36px" @click="ui.resolveConfirm(a.value)">{{ a.label }}</button>
          </template>
          <template v-else>
            <button class="btn btn-secondary" style="flex:1;height:36px" @click="ui.resolveConfirm(false)">取消</button>
            <button class="btn btn-primary confirm-ok" style="flex:1;height:36px" @click="ui.resolveConfirm(true)">确定</button>
          </template>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { useUiStore } from '../stores/ui.js'
const ui = useUiStore()
</script>

<style scoped>
.toast-stack {
  position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
  z-index: 4000; display: flex; flex-direction: column; gap: 8px; align-items: center;
  pointer-events: none;
}
.toast-bar {
  display: flex; align-items: center; gap: 8px;
  background: var(--bg-card); color: var(--text-primary);
  border: 1px solid var(--border-light); border-radius: var(--radius-lg);
  box-shadow: var(--shadow-floating);
  padding: 10px 16px; min-width: 220px; max-width: min(480px, calc(100vw - 32px));
  font-size: var(--text-md); pointer-events: auto;
  animation: toast-in .22s ease-out;
}
@keyframes toast-in { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: none; } }
.toast-success svg { color: var(--success); }
.toast-error svg { color: var(--error); }
.toast-info svg { color: var(--info); }
.toast-theme { background: var(--panel); }
.toast-msg { flex: 1; line-height: 1.4; }
.toast-close {
  display: flex; align-items: center; justify-content: center;
  width: 22px; height: 22px; border-radius: var(--radius-full);
  border: none; background: none; color: var(--text-muted); cursor: pointer; flex-shrink: 0;
}
.toast-close:hover { background: var(--bg-input); color: var(--text-primary); }

.confirm-overlay {
  position: fixed; inset: 0; z-index: 4100; background: var(--surface-overlay);
  backdrop-filter: blur(4px); display: flex; justify-content: center; align-items: center; padding: 16px;
}
.confirm-panel {
  background: var(--bg-card); border: 1px solid var(--border-light);
  border-radius: var(--radius-lg); padding: 24px; width: 380px; max-width: 100%;
}
.confirm-title { font-size: var(--text-xl); font-weight: 600; margin-bottom: 8px; }
.confirm-msg { font-size: var(--text-md); color: var(--text-secondary); line-height: 1.6; margin-bottom: 20px; }
.confirm-actions { display: flex; gap: 8px; }
.confirm-actions .btn-danger { background: var(--error); color: #fff; }
</style>
