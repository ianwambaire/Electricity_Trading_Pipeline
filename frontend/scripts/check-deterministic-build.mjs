// Two local release builds, fresh disposable output paths, byte-for-byte comparison.
import { spawnSync } from 'node:child_process'
import { mkdtemp, readdir, readFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, relative } from 'node:path'
import { createHash } from 'node:crypto'
const index = process.argv.indexOf('--origin')
const origin = index >= 0 ? process.argv[index + 1] : process.env.POWERFLOW_RELEASE_ORIGIN
if (!origin) throw Error('An explicit candidate --origin is required')
const workspace = await mkdtemp(join(tmpdir(), 'powerflow-build-repro-'))
async function inventory(root, current = root) {
  const result = {}
  for (const entry of await readdir(current, { withFileTypes: true })) {
    const path = join(current, entry.name)
    if (entry.isDirectory()) Object.assign(result, await inventory(root, path))
    else if (entry.isFile()) result[relative(root, path)] = createHash('sha256').update(await readFile(path)).digest('hex')
    else throw Error('Unexpected release artifact type')
  }
  return Object.fromEntries(Object.entries(result).sort(([a], [b]) => a.localeCompare(b)))
}
const inventories = []
for (const name of ['first', 'second']) {
  const path = join(workspace, name)
  const status = spawnSync(process.execPath, ['scripts/release-build.mjs', '--origin', origin, '--out-dir', path], { stdio: 'inherit' }).status
  if (status !== 0) process.exit(status ?? 1)
  inventories.push(await inventory(path))
}
if (JSON.stringify(inventories[0]) !== JSON.stringify(inventories[1])) throw Error('Release builds differ')
console.log(JSON.stringify({ deterministic: true, files: Object.keys(inventories[0]).length, candidateOrigin: origin, workspace, deployed: false }))
