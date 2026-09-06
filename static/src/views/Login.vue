<template>
  <div class="login-page">
    <div class="login-card">
      <h1 class="login-title">{{ store.siteName }}</h1>
      <p class="login-sub">多项目媒体库 · 请登录后访问</p>

      <div class="tab-row" role="tablist">
        <button class="tab" :class="{ active: mode === 'login' }" @click="mode = 'login'">登录</button>
        <button class="tab" :class="{ active: mode === 'register' }" @click="mode = 'register'">注册</button>
      </div>

      <!-- 登录 -->
      <form v-if="mode === 'login'" class="form" @submit.prevent="doLogin">
        <label class="field">
          <span>用户名</span>
          <input v-model.trim="username" type="text" autocomplete="username" placeholder="用户名" />
        </label>
        <label class="field">
          <span>密码</span>
          <div class="pwd-wrap">
            <input v-model="password" :type="showPwd ? 'text' : 'password'" autocomplete="current-password" placeholder="密码" />
            <button type="button" class="pwd-eye" @click="showPwd = !showPwd" :title="showPwd ? '隐藏密码' : '显示密码'">
              <svg v-if="!showPwd" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z"/><circle cx="12" cy="12" r="3"/></svg>
              <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
            </button>
          </div>
        </label>
        <p v-if="loginMsg" class="msg" :class="{ ok: loginOk, warn: pendingFlag, err: !loginOk && !pendingFlag }">{{ loginMsg }}</p>
        <button class="submit" type="submit" :disabled="busy">{{ busy ? '登录中…' : '登录' }}</button>
      </form>

      <!-- 注册 -->
      <form v-else class="form" @submit.prevent="doRegister">
        <label class="field">
          <span>用户名</span>
          <input v-model.trim="regUsername" type="text" autocomplete="username" placeholder="设置用户名" />
        </label>
        <label class="field">
          <span>密码</span>
          <div class="pwd-wrap">
            <input v-model="regPassword" :type="showPwd ? 'text' : 'password'" autocomplete="new-password" placeholder="设置密码（至少 6 位）" />
            <button type="button" class="pwd-eye" @click="showPwd = !showPwd" :title="showPwd ? '隐藏密码' : '显示密码'">
              <svg v-if="!showPwd" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z"/><circle cx="12" cy="12" r="3"/></svg>
              <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
            </button>
          </div>
        </label>
        <p v-if="regMsg" class="msg" :class="{ ok: regOk }">{{ regMsg }}</p>
        <button class="submit" type="submit" :disabled="busy || regOk">{{ busy ? '提交中…' : '提交注册' }}</button>
        <p class="hint">提交后需管理员批准方可登录</p>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAppStore } from '../stores/app.js'

const store = useAppStore()
const router = useRouter()
const route = useRoute()

const mode = ref('login')
const username = ref('')
const password = ref('')
const regUsername = ref('')
const regPassword = ref('')
const showPwd = ref(false)
const busy = ref(false)
const loginMsg = ref('')
const loginOk = ref(false)
const pendingFlag = ref(false)
const regMsg = ref('')
const regOk = ref(false)

watch(mode, () => { loginMsg.value = ''; regMsg.value = ''; pendingFlag.value = false })

async function doLogin() {
  if (!username.value || !password.value) {
    loginMsg.value = '请输入用户名和密码'
    loginOk.value = false
    pendingFlag.value = false
    return
  }
  busy.value = true
  loginMsg.value = ''
  try {
    const res = await store.login(username.value, password.value)
    if (res.ok) {
      loginOk.value = true
      const redirect = route.query.redirect || '/'
      router.push(redirect)
      return
    }
    loginOk.value = false
    pendingFlag.value = !!res.pending
    if (res.pending) {
      loginMsg.value = '账号待管理员批准，请等待管理员在权限管理页批准后再登录'
    } else if (res.rejected) {
      loginMsg.value = '注册申请已被管理员拒绝，该账号无法登录'
    } else {
      loginMsg.value = res.error || '登录失败'
    }
  } catch (e) {
    loginOk.value = false
    pendingFlag.value = false
    loginMsg.value = e.message || '登录失败'
  } finally {
    busy.value = false
  }
}

async function doRegister() {
  regMsg.value = ''
  regOk.value = false
  if (!regUsername.value || !regPassword.value) {
    regMsg.value = '请填写用户名和密码'
    return
  }
  if (regPassword.value.length < 6) {
    regMsg.value = '密码至少 6 位'
    return
  }
  busy.value = true
  try {
    const res = await store.register(regUsername.value, regPassword.value)
    if (res.ok) {
      regOk.value = true
      regMsg.value = '已提交，等待管理员批准。批准后即可登录。'
    } else {
      regMsg.value = res.error || '注册失败'
    }
  } catch (e) {
    regMsg.value = e.message || '注册失败'
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex; align-items: center; justify-content: center;
  padding: 20px;
}
.login-card {
  width: min(400px, 100%);
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-floating);
  padding: 32px 30px 26px;
}
.login-title {
  margin: 0 0 4px; font-size: 24px; text-align: center;
  color: var(--text-primary); letter-spacing: 1px;
}
.login-sub {
  margin: 0 0 20px; text-align: center;
  font-size: var(--text-base); color: var(--text-secondary);
}
.tab-row {
  display: flex; gap: 6px; margin-bottom: 18px;
  background: var(--bg-input); border: 1px solid var(--border);
  border-radius: var(--radius-md); padding: 4px;
}
.tab {
  flex: 1; height: 36px; border: none; border-radius: var(--radius-sm);
  background: none; color: var(--text-secondary); font-size: var(--text-base); cursor: pointer;
}
.tab.active { background: var(--accent); color: #fff; font-weight: 600; }
.form { display: flex; flex-direction: column; gap: 14px; }
.field { display: flex; flex-direction: column; gap: 5px; }
.field span { font-size: var(--text-base); font-weight: 500; color: var(--text-secondary); }
.field input {
  height: 40px; padding: 0 12px;
  background: var(--bg-input); border: 1px solid var(--border);
  border-radius: var(--radius-sm); color: var(--text-primary); font-size: var(--text-base);
  width: 100%; box-sizing: border-box;
  transition: border-color var(--duration-fast), box-shadow var(--duration-fast);
}
.field input:focus {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 2px rgba(255, 71, 87, 0.18);
}
.field input::placeholder {
  color: var(--text-muted);
  font-size: var(--text-sm);
  opacity: 0.85;
}
.pwd-wrap { position: relative; display: flex; }
.pwd-eye {
  position: absolute; right: 8px; top: 50%; transform: translateY(-50%);
  width: 28px; height: 28px; border: none; background: none; cursor: pointer;
  color: var(--text-secondary); display: flex; align-items: center; justify-content: center;
  border-radius: var(--radius-sm);
}
.pwd-eye:hover { color: var(--text-primary); background: var(--bg-input); }
.msg { margin: 0; font-size: var(--text-sm); line-height: 1.5; }
.msg.ok { color: var(--success); }
.msg.warn { color: var(--warning, var(--accent)); }
.msg.err { color: var(--error); }
.submit {
  height: 42px; border: none; border-radius: var(--radius-sm);
  background: var(--accent); color: #fff; font-size: var(--text-md); font-weight: 600; cursor: pointer;
}
.submit:disabled { opacity: 0.6; cursor: default; }
.hint { margin: 0; text-align: center; font-size: var(--text-sm); color: var(--text-muted); }
</style>
