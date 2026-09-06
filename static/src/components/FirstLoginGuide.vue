<template>
  <div class="flg-overlay" v-if="store.mustChangePassword">
    <div class="flg-panel">
      <div class="flg-head">
        <div class="flg-shield">
          <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 2 4 5v6c0 5.25 3.4 9.74 8 11 4.6-1.26 8-5.75 8-11V5l-8-3z"/>
            <path d="M12 8v4"/>
            <circle cx="12" cy="15.5" r="0.6" fill="currentColor" stroke="none"/>
          </svg>
        </div>
        <div>
          <h2>首次登录：请修改初始密码</h2>
          <p class="flg-sub">系统检测到该账号仍在使用初始密码。为保障安全，请先修改密码（可同时修改用户名）后继续使用；修改完成前，每次登录都会出现此引导。</p>
        </div>
      </div>

      <div class="flg-form">
        <label class="flg-field">
          <span>新用户名</span>
          <input v-model.trim="newUsername" type="text" autocomplete="username" placeholder="输入新的账号名称" />
        </label>
        <label class="flg-field">
          <span>当前密码</span>
          <input v-model="oldPassword" type="password" autocomplete="current-password" placeholder="admin123" />
        </label>
        <label class="flg-field">
          <span>新密码</span>
          <input v-model="newPassword" type="password" autocomplete="new-password" placeholder="至少 6 位" />
        </label>
        <label class="flg-field">
          <span>确认新密码</span>
          <input v-model="newPassword2" type="password" autocomplete="new-password" placeholder="再次输入新密码" />
        </label>
      </div>

      <p v-if="error" class="flg-error">{{ error }}</p>
      <p v-if="okMsg" class="flg-ok">{{ okMsg }}</p>

      <div class="flg-actions">
        <button class="btn primary" :disabled="busy" @click="submit">
          {{ busy ? '提交中…' : '完成修改并继续' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '../stores/app.js'
import { useUiStore } from '../stores/ui.js'

const store = useAppStore()
const ui = useUiStore()
const router = useRouter()

const newUsername = ref(store.currentUser?.username || '')
const oldPassword = ref('')
const newPassword = ref('')
const newPassword2 = ref('')
const error = ref('')
const okMsg = ref('')
const busy = ref(false)

async function submit() {
  error.value = ''
  okMsg.value = ''
  if (!newUsername.value) { error.value = '请输入新用户名'; return }
  if (!oldPassword.value) { error.value = '请输入当前密码'; return }
  if (newPassword.value.length < 6) { error.value = '新密码至少 6 位'; return }
  if (newPassword.value !== newPassword2.value) { error.value = '两次输入的新密码不一致'; return }
  busy.value = true
  try {
    // 先改密码（后端改密成功会将 must_change_password 置 0），再改用户名（同一 cookie 会话内完成）
    await store.changePassword(oldPassword.value, newPassword.value)
    if (newUsername.value !== store.currentUser?.username) {
      await store.changeUsername(newUsername.value)
    }
    store.completeOnboarding()
    okMsg.value = '修改成功，即将继续…'
    ui.toast('默认账号信息已更新', 'success')
    setTimeout(() => { router.go(0) }, 800)
  } catch (e) {
    error.value = e.message || '修改失败'
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.flg-overlay {
  position: fixed; inset: 0; z-index: 3600;
  background: rgba(0, 0, 0, 0.62);
  display: flex; align-items: center; justify-content: center;
  padding: 20px;
}
.flg-panel {
  width: min(480px, 100%);
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-floating);
  padding: 26px 26px 22px;
}
.flg-head { display: flex; gap: 14px; align-items: flex-start; margin-bottom: 18px; }
.flg-shield {
  flex: none; width: 48px; height: 48px; border-radius: var(--radius-md);
  display: flex; align-items: center; justify-content: center;
  background: var(--accent-weak, rgba(255, 138, 76, 0.14));
  color: var(--accent);
}
.flg-head h2 { margin: 0 0 6px; font-size: 17px; color: var(--text-primary); }
.flg-sub { margin: 0; font-size: 12.5px; line-height: 1.6; color: var(--text-secondary); }
.flg-form { display: flex; flex-direction: column; gap: 12px; }
.flg-field { display: flex; flex-direction: column; gap: 5px; }
.flg-field span { font-size: 12px; color: var(--text-secondary); }
.flg-field input {
  height: 38px; padding: 0 12px;
  background: var(--bg-input); border: 1px solid var(--border);
  border-radius: var(--radius-sm); color: var(--text-primary); font-size: 14px;
  transition: border-color var(--duration-fast), box-shadow var(--duration-fast);
}
.flg-field input:focus {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 2px rgba(255, 71, 87, 0.18);
}
.flg-field input::placeholder {
  color: var(--text-muted);
  font-size: 13px;
  opacity: 0.85;
}
.flg-error { margin: 12px 0 0; font-size: 12.5px; color: var(--error); }
.flg-ok { margin: 12px 0 0; font-size: 12.5px; color: var(--success); }
.flg-actions { margin-top: 18px; display: flex; justify-content: flex-end; }
.btn {
  height: 38px; padding: 0 20px; border: none; border-radius: var(--radius-sm);
  font-size: 13.5px; cursor: pointer; color: #fff;
}
.btn.primary { background: var(--accent); }
.btn.primary:disabled { opacity: 0.6; cursor: default; }
</style>
