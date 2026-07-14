import { createHash, randomInt, randomUUID } from 'crypto'
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync } from 'fs'
import { dirname, relative, resolve } from 'path'
import { fileURLToPath } from 'url'

const here = dirname(fileURLToPath(import.meta.url))
export const repositoryRoot = resolve(here, '../../..')
export const frontendRoot = resolve(repositoryRoot, 'frontend')

export const e2eRunId = process.env.E2E_RUN_ID || `${Date.now()}-${randomUUID().slice(0, 8)}`
process.env.E2E_RUN_ID = e2eRunId

export const e2eRunRoot = resolve(repositoryRoot, 'storage', 'e2e-runs', e2eRunId)
export const e2eDatabasePath = resolve(e2eRunRoot, 'e2e.db')
export const e2eDatabaseUrl = `sqlite:///${e2eDatabasePath.replace(/\\/g, '/')}`
export const e2eUploadDir = resolve(e2eRunRoot, 'uploads')
export const normalUploadDir = resolve(repositoryRoot, 'storage', 'uploads')
export const e2eArtifactDir = resolve(frontendRoot, 'test-results', 'e2e-runtime', e2eRunId)
export const e2eManifestPath = resolve(e2eArtifactDir, 'runtime-manifest.json')
export const e2eTeardownPath = resolve(e2eArtifactDir, 'teardown-result.json')

function choosePort(envName: string, base: number): number {
  const supplied = process.env[envName]
  if (supplied) return Number(supplied)
  return base + randomInt(0, 800)
}

export const backendPort = choosePort('E2E_BACKEND_PORT', 18000)
export const workerPort = choosePort('E2E_WORKER_PORT', 19000)
export const frontendPort = choosePort('E2E_FRONTEND_PORT', 20000)

process.env.E2E_BACKEND_PORT = String(backendPort)
process.env.E2E_WORKER_PORT = String(workerPort)
process.env.E2E_FRONTEND_PORT = String(frontendPort)
process.env.E2E_DATABASE_URL = e2eDatabaseUrl
process.env.E2E_UPLOAD_DIR = e2eUploadDir
process.env.E2E_RUN_ROOT = e2eRunRoot
// Expose the exact same isolated values to test helpers and child processes.
process.env.DATABASE_URL = e2eDatabaseUrl
process.env.UPLOAD_DIR = e2eUploadDir
process.env.ENVIRONMENT = 'e2e'

mkdirSync(e2eRunRoot, { recursive: true })
mkdirSync(e2eUploadDir, { recursive: true })
mkdirSync(e2eArtifactDir, { recursive: true })

export interface SnapshotEntry {
  path: string
  size: number
  sha256: string
}

export function snapshotDirectory(root: string): SnapshotEntry[] {
  if (!existsSync(root)) return []
  const entries: SnapshotEntry[] = []

  const walk = (dir: string) => {
    for (const name of readdirSync(dir).sort()) {
      const absolute = resolve(dir, name)
      const stat = statSync(absolute)
      if (stat.isDirectory()) {
        walk(absolute)
      } else if (stat.isFile()) {
        const payload = readFileSync(absolute)
        entries.push({
          path: relative(root, absolute).replace(/\\/g, '/'),
          size: stat.size,
          sha256: createHash('sha256').update(payload).digest('hex'),
        })
      }
    }
  }

  walk(root)
  return entries
}

export function assertIsolatedPath(candidate: string): void {
  const normalizedRoot = resolve(e2eRunRoot)
  const normalized = resolve(candidate)
  const separator = process.platform === 'win32' ? '\\' : '/'
  if (normalized !== normalizedRoot && !normalized.startsWith(`${normalizedRoot}${separator}`)) {
    throw new Error(`E2E path escapes the isolated run root: ${candidate}`)
  }
  const normalRoot = resolve(normalUploadDir)
  if (normalized === normalRoot || normalized.startsWith(`${normalRoot}${separator}`)) {
    throw new Error(`E2E path points at normal uploads: ${candidate}`)
  }
}
