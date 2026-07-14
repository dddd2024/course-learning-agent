import { createHash, randomBytes } from 'crypto'
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'fs'
import { createServer } from 'net'
import { dirname, relative, resolve, sep } from 'path'

export interface ProtectedPathSnapshot {
  path: string
  exists: boolean
  kind: 'missing' | 'file' | 'directory'
  digest: string | null
}

export interface E2ERuntimeManifest {
  runId: string
  repoRoot: string
  runRoot: string
  databaseUrl: string
  databasePath: string
  uploadDir: string
  parsedDir: string
  backendPort: number
  workerPort: number
  frontendPort: number
  apiBase: string
  protectedPaths: string[]
  protectedSnapshot: ProtectedPathSnapshot[]
}

function digestFile(path: string): string {
  return createHash('sha256').update(readFileSync(path)).digest('hex')
}

function digestDirectory(root: string): string {
  const hash = createHash('sha256')

  const visit = (current: string) => {
    for (const entry of readdirSync(current, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const absolute = resolve(current, entry.name)
      const rel = relative(root, absolute).split(sep).join('/')
      hash.update(`${entry.isDirectory() ? 'D' : 'F'}:${rel}\n`)
      if (entry.isDirectory()) {
        visit(absolute)
      } else if (entry.isFile()) {
        const stats = statSync(absolute)
        hash.update(`${stats.size}:`)
        hash.update(readFileSync(absolute))
      }
    }
  }

  visit(root)
  return hash.digest('hex')
}

export function captureProtectedSnapshot(paths: string[]): ProtectedPathSnapshot[] {
  return paths.map((path) => {
    if (!existsSync(path)) {
      return { path, exists: false, kind: 'missing', digest: null }
    }
    const stats = statSync(path)
    if (stats.isFile()) {
      return { path, exists: true, kind: 'file', digest: digestFile(path) }
    }
    if (stats.isDirectory()) {
      return { path, exists: true, kind: 'directory', digest: digestDirectory(path) }
    }
    return { path, exists: true, kind: 'file', digest: null }
  })
}

async function canBind(port: number): Promise<boolean> {
  return await new Promise((resolveResult) => {
    const server = createServer()
    server.unref()
    server.once('error', () => resolveResult(false))
    server.listen(port, '127.0.0.1', () => {
      server.close(() => resolveResult(true))
    })
  })
}

async function allocatePort(envName: string, preferred: number): Promise<number> {
  const explicit = process.env[envName]
  if (explicit) {
    const port = Number(explicit)
    if (!Number.isInteger(port) || port < 1 || port > 65_535) {
      throw new Error(`${envName} must be a valid TCP port`)
    }
    if (!(await canBind(port))) {
      throw new Error(`${envName}=${port} is already in use; refusing to reuse an existing server`)
    }
    return port
  }

  for (let port = preferred; port < preferred + 100; port += 1) {
    if (await canBind(port)) return port
  }
  throw new Error(`Could not allocate a free E2E port starting at ${preferred}`)
}

function sqlitePath(databaseUrl: string): string {
  const prefix = 'sqlite:///'
  if (!databaseUrl.startsWith(prefix)) {
    throw new Error('E2E_DATABASE_URL must be a sqlite:/// URL')
  }
  return resolve(databaseUrl.slice(prefix.length))
}

function requireRunPath(path: string, runRoot: string, label: string): string {
  const normalized = resolve(path)
  const normalizedRoot = resolve(runRoot)
  if (normalized !== normalizedRoot && !normalized.startsWith(`${normalizedRoot}${sep}`)) {
    throw new Error(`${label} must live under the unique E2E run root: ${normalizedRoot}`)
  }
  return normalized
}

export async function createE2ERuntime(repoRoot: string): Promise<E2ERuntimeManifest> {
  const runId = process.env.E2E_RUN_ID?.trim()
    || `${Date.now()}-${process.pid}-${randomBytes(4).toString('hex')}`
  if (!/^[A-Za-z0-9._-]+$/.test(runId)) {
    throw new Error('E2E_RUN_ID contains unsafe path characters')
  }

  const runRoot = resolve(repoRoot, '.e2e-runs', runId)
  mkdirSync(runRoot, { recursive: true })

  const generatedDatabasePath = resolve(runRoot, 'e2e.db')
  const databaseUrl = process.env.E2E_DATABASE_URL || `sqlite:///${generatedDatabasePath.split(sep).join('/')}`
  const databasePath = requireRunPath(sqlitePath(databaseUrl), runRoot, 'E2E database')
  const uploadDir = requireRunPath(process.env.E2E_UPLOAD_DIR || resolve(runRoot, 'uploads'), runRoot, 'E2E upload directory')
  const parsedDir = requireRunPath(process.env.E2E_PARSED_DIR || resolve(runRoot, 'parsed'), runRoot, 'E2E parsed directory')

  const backendPort = await allocatePort('E2E_BACKEND_PORT', 8000)
  const workerPort = await allocatePort('E2E_WORKER_PORT', 8001)
  const frontendPort = await allocatePort('E2E_FRONTEND_PORT', 5173)
  if (new Set([backendPort, workerPort, frontendPort]).size !== 3) {
    throw new Error('E2E backend, worker, and frontend ports must be distinct')
  }

  mkdirSync(dirname(databasePath), { recursive: true })
  mkdirSync(uploadDir, { recursive: true })
  mkdirSync(parsedDir, { recursive: true })

  const protectedPaths = [
    resolve(repoRoot, 'backend', 'course_assistant.db'),
    resolve(repoRoot, 'storage', 'uploads'),
    resolve(repoRoot, 'storage', 'parsed'),
  ]

  const manifest: E2ERuntimeManifest = {
    runId,
    repoRoot: resolve(repoRoot),
    runRoot,
    databaseUrl,
    databasePath,
    uploadDir,
    parsedDir,
    backendPort,
    workerPort,
    frontendPort,
    apiBase: `http://127.0.0.1:${backendPort}/api/v1`,
    protectedPaths,
    protectedSnapshot: captureProtectedSnapshot(protectedPaths),
  }

  const manifestPath = resolve(runRoot, 'runtime.json')
  writeFileSync(manifestPath, JSON.stringify(manifest, null, 2), 'utf-8')

  process.env.E2E_RUN_ID = runId
  process.env.E2E_DATABASE_URL = databaseUrl
  process.env.E2E_UPLOAD_DIR = uploadDir
  process.env.E2E_PARSED_DIR = parsedDir
  process.env.E2E_BACKEND_PORT = String(backendPort)
  process.env.E2E_WORKER_PORT = String(workerPort)
  process.env.E2E_FRONTEND_PORT = String(frontendPort)
  process.env.E2E_API_BASE = manifest.apiBase
  process.env.E2E_RUNTIME_MANIFEST = manifestPath

  return manifest
}

export function readRuntimeManifest(): E2ERuntimeManifest {
  const manifestPath = process.env.E2E_RUNTIME_MANIFEST
  if (!manifestPath || !existsSync(manifestPath)) {
    throw new Error('E2E_RUNTIME_MANIFEST is missing or unreadable')
  }
  return JSON.parse(readFileSync(manifestPath, 'utf-8')) as E2ERuntimeManifest
}

export function cleanupRuntime(manifest: E2ERuntimeManifest): void {
  for (const suffix of ['', '-wal', '-shm', '-journal']) {
    rmSync(`${manifest.databasePath}${suffix}`, { force: true })
  }
  rmSync(manifest.runRoot, { recursive: true, force: true })
  const runsRoot = dirname(manifest.runRoot)
  if (existsSync(runsRoot) && readdirSync(runsRoot).length === 0) {
    rmSync(runsRoot, { recursive: true, force: true })
  }
}
