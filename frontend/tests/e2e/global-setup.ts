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
}
