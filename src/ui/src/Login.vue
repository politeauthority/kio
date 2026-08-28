<template>
  <div class="login-wrap">
    <div class="login-card">
      <div class="sidebar-brand" style="justify-content: center; margin-bottom: 1.5rem">
        <span class="brand-dot"></span>
        kio
      </div>

      <template v-if="oidc">
        <button class="btn btn-primary w-100" type="button" :disabled="redirecting" @click="ssoLogin">
          {{ redirecting ? 'Redirecting…' : `Sign in with ${oidc.display_name}` }}
        </button>
        <p v-if="callbackError" class="login-error">Sign-in didn't complete. Please try again.</p>
        <div v-if="devLogin" class="login-divider"><span>or</span></div>
      </template>

      <form v-if="devLogin" @submit.prevent="submit" class="login-form">
        <div class="form-group">
          <label class="form-label">Username</label>
          <input v-model="username" class="form-control" type="text" autocomplete="username" required :autofocus="!oidc" />
        </div>
        <div class="form-group">
          <label class="form-label">Password</label>
          <input v-model="password" class="form-control" type="password" autocomplete="current-password" required />
        </div>
        <p v-if="error" class="login-error">{{ error }}</p>
        <button class="btn w-100" :class="oidc ? 'btn-secondary' : 'btn-primary'" type="submit" :disabled="loading">
          {{ loading ? 'Signing in…' : 'Sign in' }}
        </button>
      </form>

      <p v-if="!oidc && !devLogin" class="login-error">
        No login method is configured. Set <code>AUTHENTIK_ISSUER</code> / <code>AUTHENTIK_CLIENT_ID</code>
        or <code>DEV_USERNAME</code> / <code>DEV_PASSWORD</code> on the API.
      </p>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { authConfig, devLogin as devLoginRequest, isAuthenticated, oidcLogin } from './auth'

const route = useRoute()
const router = useRouter()
const cfg = authConfig()
const oidc = cfg.oidc
const devLogin = cfg.dev_login

const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)
const redirecting = ref(false)
const callbackError = computed(() => route.query.error === 'callback')

// Only trust in-app paths as a return target — never an absolute URL.
const returnTo = computed(() => {
  const r = route.query.returnTo
  return typeof r === 'string' && r.startsWith('/') && !r.startsWith('//') ? r : '/'
})

onMounted(async () => {
  if (await isAuthenticated()) {
    router.replace(returnTo.value)
    return
  }
  // Authentik is the only option: skip the intermediate page entirely,
  // unless we've just bounced back here from a failed callback.
  if (oidc && !devLogin && !callbackError.value) ssoLogin()
})

async function ssoLogin() {
  redirecting.value = true
  try {
    await oidcLogin(returnTo.value)
  } catch (err) {
    console.error('OIDC redirect failed', err)
    redirecting.value = false
  }
}

async function submit() {
  error.value = ''
  loading.value = true
  try {
    await devLoginRequest(username.value, password.value)
    router.replace(returnTo.value)
  } catch {
    error.value = 'Invalid username or password.'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: var(--bg-primary);
}
.login-card {
  width: 100%;
  max-width: 340px;
  padding: 2rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.login-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.login-divider {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  color: var(--text-muted);
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.login-divider::before,
.login-divider::after {
  content: '';
  flex: 1;
  border-top: 1px solid var(--border);
}
.login-error {
  color: var(--danger);
  font-size: 0.875rem;
  margin: 0;
}
.w-100 { width: 100%; }
</style>
