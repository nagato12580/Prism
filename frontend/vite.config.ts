import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api/v1/chat/answer': { target: 'http://127.0.0.1:5175', changeOrigin: true },
      '/api/v1/ingest':      { target: 'http://127.0.0.1:5180', changeOrigin: true },
      '/api':                { target: 'http://127.0.0.1:5175', changeOrigin: true },
    },
  },
})
