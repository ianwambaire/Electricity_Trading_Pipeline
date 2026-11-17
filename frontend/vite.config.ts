import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig, loadEnv } from 'vite'
import { productionConfig } from './build/productionConfig.ts'

const devApiPort = Number(process.env.POWERFLOW_DEV_API_PORT ?? '8000')
if (!Number.isInteger(devApiPort) || devApiPort < 1024 || devApiPort > 65535) throw new Error('Invalid local API proxy port')

export default defineConfig(({ command, mode }) => {
  const publicEnv = loadEnv(mode, process.cwd(), 'VITE_')
  const manifest = command === 'build' ? productionConfig(publicEnv, process.env.POWERFLOW_RELEASE_ORIGIN) : null
  return {
  plugins: [react(), tailwindcss(), {
    name: 'powerflow-build-provenance',
    generateBundle() {
      if (manifest) this.emitFile({ type: 'asset', fileName: 'build-config.json', source: JSON.stringify(manifest, null, 2) + '\n' })
    },
  }],
  build: { sourcemap: false },
  server: { proxy: { '/api': { target: `http://127.0.0.1:${devApiPort}`, changeOrigin: true, rewrite: path => path.replace(/^\/api(?=\/|$)/, '') } } },
  }
})
