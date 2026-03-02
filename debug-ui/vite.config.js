import { defineConfig } from 'vite'
import { resolve } from 'path'

export default defineConfig({
  root: '.',
  publicDir: false,
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index-v2.html')
      }
    }
  },
  server: {
    port: 3000,
    proxy: {
      '/miniflux-ai': {
        target: 'http://localhost:5000',
        changeOrigin: true
      }
    }
  }
})