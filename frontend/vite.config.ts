import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

const devApiPort = Number(process.env.POWERFLOW_DEV_API_PORT ?? '8000')
if (!Number.isInteger(devApiPort) || devApiPort < 1024 || devApiPort > 65535) throw new Error('Invalid local API proxy port')

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { sourcemap: false },
  server: { proxy: { '/api': { target: `http://127.0.0.1:${devApiPort}`, changeOrigin: true, rewrite: path => path.replace(/^\/api(?=\/|$)/, '') } } },
})
