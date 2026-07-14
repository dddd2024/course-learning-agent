import { existsSync, readFileSync, rmSync, writeFileSync } from 'fs'
import {
  e2eArtifactDir,
  e2eManifestPath,
  e2eRunId,
  e2eRunRoot,
  e2eTeardownPath,
  normalUploadDir,
  snapshotDirectory,
} from './e2e-runtime'

function stable(value: unknown): string {
  return JSON.stringify(value)
}

export default async function globalTeardown() {
  const manifest = JSON.parse(readFileSync(e2eManifestPath, 'utf-8'))
  const after = snapshotDirectory(normalUploadDir)
  const unchanged = stable(manifest.normal_uploads_before) === stable(after)
  let cleanupPassed = false
  let cleanupError: string | null = null

  try {
    rmSync(e2eRunRoot, { recursive: true, force: true })
    cleanupPassed = !existsSync(e2eRunRoot)
  } catch (error) {
    cleanupError = error instanceof Error ? error.message : String(error)
  }

  const result = {
    run_id: e2eRunId,
    manifest_path: e2eManifestPath,
    normal_uploads_unchanged: unchanged,
    normal_uploads_after: after,
    cleanup_passed: cleanupPassed,
    cleanup_error: cleanupError,
    completed_at: new Date().toISOString(),
    passed: unchanged && cleanupPassed,
  }

  writeFileSync(e2eTeardownPath, JSON.stringify(result, null, 2), 'utf-8')

  if (!unchanged) {
    throw new Error(`E2E modified normal uploads; evidence: ${e2eArtifactDir}`)
  }
  if (!cleanupPassed) {
    throw new Error(`E2E isolated run cleanup failed; evidence: ${e2eArtifactDir}`)
  }
}
