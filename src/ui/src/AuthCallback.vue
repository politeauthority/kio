<template>
  <div class="d-flex justify-content-center align-items-center vh-100">
    <div class="spinner-border text-secondary" role="status">
      <span class="visually-hidden">Signing in…</span>
    </div>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { handleCallback } from './auth'

const router = useRouter()

onMounted(async () => {
  let dest = '/'
  try {
    dest = await handleCallback()
  } catch (err) {
    console.error('OIDC callback failed', err)
    dest = { path: '/login', query: { error: 'callback' } }
  }
  router.replace(dest)
})
</script>
