import { createHash, randomBytes } from 'crypto'
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
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
  frontendBase: string
  runtimeReportPath: string
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
  // Playwright evaluates the config in a controller and in worker processes.
  // The controller's manifest is authoritative; workers must consume it
  // rather than allocating a second database for the same run ID.
  if (process.env.E2E_RUNTIME_MANIFEST && existsSync(process.env.E2E_RUNTIME_MANIFEST)) {
    return readRuntimeManifest()
  }
  const runId = process.env.E2E_RUN_ID?.trim()
    || `${Date.now()}-${process.pid}-${randomBytes(4).toString('hex')}`
  if (!/^[A-Za-z0-9._-]+$/.test(runId)) {
    throw new Error('E2E_RUN_ID contains unsafe path characters')
  }

  // E2E data must never be created below the repository's normal storage
  // tree.  CI may explicitly provide individual paths, but they still have
  // to be descendants of this per-run system-temporary root.
  const runRoot = resolve(tmpdir(), 'course-learning-agent-e2e', runId)
  mkdirSync(runRoot, { recursive: true })
  writeFileSync(resolve(runRoot, '.course-learning-agent-e2e'), `${runId}\n`, 'utf-8')

  const generatedDatabasePath = resolve(runRoot, 'e2e.db')
  const databaseUrl = process.env.E2E_DATABASE_URL || `sqlite:///${generatedDatabasePath.split(sep).join('/')}`
  const databasePath = requireRunPath(sqlitePath(databaseUrl), runRoot, 'E2E database')
  if (existsSync(databasePath)) {
    throw new Error(`E2E database already exists for this run: ${databasePath}`)
  }
  const uploadDir = requireRunPath(process.env.E2E_UPLOAD_DIR || resolve(runRoot, 'uploads'), runRoot, 'E2E upload directory')
  const parsedDir = requireRunPath(process.env.E2E_PARSED_DIR || resolve(runRoot, 'parsed'), runRoot, 'E2E parsed directory')

  const backendPort = await allocatePort('E2E_BACKEND_PORT', 8000)
  // Use disjoint search ranges.  A probe is released before the child
  // process binds it, so independently probing adjacent ports can otherwise
  // select the same free port three times.
  const workerPort = await allocatePort('E2E_WORKER_PORT', 8100)
  const frontendPort = await allocatePort('E2E_FRONTEND_PORT', 8200)
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
    frontendBase: `http://127.0.0.1:${frontendPort}`,
    runtimeReportPath: resolve(repoRoot, 'frontend', 'test-results', 'e2e-runtime.json'),
    protectedPaths,
    protectedSnapshot: captureProtectedSnapshot(protectedPaths),
  }

  const manifestPath = resolve(runRoot, 'runtime.json')
  writeFileSync(manifestPath, JSON.stringify(manifest, null, 2), 'utf-8')
  mkdirSync(dirname(manifest.runtimeReportPath), { recursive: true })
  writeFileSync(manifest.runtimeReportPath, JSON.stringify(manifest, null, 2), 'utf-8')

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

export function cleanupRuntime(manifest: E2ERuntimeManifest): boolean {
  let removed = true
  for (const suffix of ['', '-wal', '-shm', '-journal']) {
    try {
      rmSync(`${manifest.databasePath}${suffix}`, { force: true, maxRetries: 5, retryDelay: 200 })
    } catch {
      // Playwright stops webServer children after global teardown on Windows.
      // Keep the report honest and let the per-run temporary root be removed
      // by the OS if a SQLite handle is still being released.
      removed = false
    }
  }
  try {
    rmSync(manifest.runRoot, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 })
  } catch {
    removed = false
  }
  const runsRoot = dirname(manifest.runRoot)
  if (existsSync(runsRoot) && readdirSync(runsRoot).length === 0) {
    rmSync(runsRoot, { recursive: true, force: true })
  }
  return removed
}
