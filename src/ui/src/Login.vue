<template>
  <div class="login-wrap">
    <form class="login-card" @submit.prevent="submit">
      <div class="sidebar-brand" style="justify-content: center; margin-bottom: 1.5rem">
        <span class="brand-dot"></span>
        kio
      </div>
      <div class="form-group">
        <label class="form-label">Username</label>
        <input v-model="username" class="form-control" type="text" autocomplete="username" required autofocus />
      </div>
      <div class="form-group">
        <label class="form-label">Password</label>
        <input v-model="password" class="form-control" type="password" autocomplete="current-password" required />
      </div>
      <p v-if="error" class="login-error">{{ error }}</p>
      <button class="btn btn-primary w-100" type="submit" :disabled="loading">
        {{ loading ? 'Signing in…' : 'Sign in' }}
      </button>
    </form>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { devLogin } from './auth'

const router = useRouter()
const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

async function submit() {
  error.value = ''
  loading.value = true
  try {
    await devLogin(username.value, password.value)
    router.replace('/')
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
.login-error {
  color: var(--danger);
  font-size: 0.875rem;
  margin: 0;
}
.w-100 { width: 100%; }
</style>
