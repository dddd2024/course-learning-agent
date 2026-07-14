import { mkdirSync } from 'fs'
import { resolve, sep } from 'path'

import { readRuntimeManifest } from './e2e-runtime'

export default async function globalSetup(): Promise<void> {
  const runtime = readRuntimeManifest()
  const runRoot = resolve(runtime.runRoot)

  const assertUnderRunRoot = (path: string, label: string) => {
    const normalized = resolve(path)
    if (normalized !== runRoot && !normalized.startsWith(`${runRoot}${sep}`)) {
      throw new Error(`${label} escaped the E2E run root: ${normalized}`)
    }
  }

  assertUnderRunRoot(runtime.databasePath, 'database')
  assertUnderRunRoot(runtime.uploadDir, 'upload directory')
  assertUnderRunRoot(runtime.parsedDir, 'parsed directory')

  if (process.env.E2E_DATABASE_URL !== runtime.databaseUrl) {
    throw new Error('E2E_DATABASE_URL changed after Playwright configuration')
  }
  if (resolve(process.env.E2E_UPLOAD_DIR || '') !== resolve(runtime.uploadDir)) {
    throw new Error('E2E_UPLOAD_DIR changed after Playwright configuration')
  }
  if (resolve(process.env.E2E_PARSED_DIR || '') !== resolve(runtime.parsedDir)) {
    throw new Error('E2E_PARSED_DIR changed after Playwright configuration')
  }

  mkdirSync(runtime.uploadDir, { recursive: true })
  mkdirSync(runtime.parsedDir, { recursive: true })

  const [backendResponse, workerResponse] = await Promise.all([
    fetch(`${runtime.apiBase}/health`),
    fetch(`http://127.0.0.1:${runtime.workerPort}/`),
  ])
  if (!backendResponse.ok || !workerResponse.ok) {
    throw new Error('E2E backend or worker health endpoint is unavailable')
  }
  const [backend, worker] = await Promise.all([backendResponse.json(), workerResponse.json()]) as Array<{ e2e?: Record<string, string> }>
  const fields = ['run_id', 'database_fingerprint', 'upload_dir_fingerprint', 'parsed_dir_fingerprint']
  for (const field of fields) {
    if (!backend.e2e || backend.e2e[field] !== worker.e2e?.[field]) {
      throw new Error(`E2E runtime mismatch for ${field}`)
    }
  }
  if (backend.e2e?.run_id !== runtime.runId) {
    throw new Error('E2E backend did not start with the allocated run ID')
  }
}
