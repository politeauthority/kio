import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': {
        target: process.env.DEV_API_TARGET || 'http://localhost:8000',
        rewrite: path => path.replace(/^\/api/, ''),
      },
    },
  },
})
