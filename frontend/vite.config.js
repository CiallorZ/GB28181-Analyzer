import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) }
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8788',
        changeOrigin: true
      }
    }
  },
  // vite preview 也把 /api 转给后端，便于按生产构建验收
  preview: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8788',
        changeOrigin: true
      }
    }
  },
  build: {
    manifest: true,
    outDir: 'dist',
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (id.includes('/echarts/') || id.includes('/zrender/')) return 'echarts'
          if (id.includes('/vue/') || id.includes('/@vue/') ||
              id.includes('/vue-router/') || id.includes('/pinia/')) return 'vue'
        }
      }
    }
  }
})
