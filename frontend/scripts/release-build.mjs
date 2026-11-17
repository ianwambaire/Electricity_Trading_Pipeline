// Local build only. No credentials, Cognito settings, network or deployment.
import { spawnSync } from 'node:child_process'
const originArg = process.argv.indexOf('--origin')
const origin = originArg >= 0 ? process.argv[originArg + 1] : process.env.POWERFLOW_RELEASE_ORIGIN
if (!origin) throw Error('Use --origin https://approved-host; this builds a candidate, not an approved Cognito registration')
const parsed = new URL(origin)
if (parsed.protocol !== 'https:' || parsed.origin !== origin || ['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname) || parsed.hostname.endsWith('.localhost')) throw Error('An explicit HTTPS origin is required')
const outIndex = process.argv.indexOf('--out-dir')
const outDir = outIndex >= 0 ? process.argv[outIndex + 1] : 'dist'
if (!outDir) throw Error('Missing output directory')
const env = { ...process.env, POWERFLOW_RELEASE_ORIGIN: origin, VITE_COGNITO_REDIRECT_URI: `${origin}/auth/callback`, VITE_COGNITO_POST_LOGOUT_REDIRECT_URI: `${origin}/` }
for (const args of [['node_modules/typescript/bin/tsc', '-b'], ['node_modules/vite/bin/vite.js', 'build', '--outDir', outDir], ['scripts/check-build.mjs', '--release', '--origin', origin, '--dist', outDir]]) {
  const result = spawnSync(process.execPath, args, { env, stdio: 'inherit' })
  if (result.status !== 0) process.exit(result.status ?? 1)
}
