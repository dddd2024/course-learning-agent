import { mkdirSync, writeFileSync } from 'fs'
import { dirname, resolve } from 'path'

import { captureProtectedSnapshot, cleanupRuntime, readRuntimeManifest } from './e2e-runtime'

export default async function globalTeardown(): Promise<void> {
  const runtime = readRuntimeManifest()
  const after = captureProtectedSnapshot(runtime.protectedPaths)
  const beforeJson = JSON.stringify(runtime.protectedSnapshot)
  const afterJson = JSON.stringify(after)

  // Playwright invokes global teardown before it tears down webServer
  // children.  Ask only the dynamically allocated E2E services to stop so
  // Windows releases SQLite file handles before the cleanup proof runs.
  await Promise.allSettled([
    fetch(`${runtime.apiBase}/e2e/shutdown`, { method: 'POST' }),
    fetch(`http://127.0.0.1:${runtime.workerPort}/shutdown`, { method: 'POST' }),
  ])
  await new Promise((resolveDelay) => setTimeout(resolveDelay, 1_000))
  const temporaryResourcesRemoved = cleanupRuntime(runtime)
  const unchanged = beforeJson === afterJson
  const reportPath = resolve(runtime.repoRoot, 'frontend', 'test-results', 'e2e-teardown.json')
  mkdirSync(dirname(reportPath), { recursive: true })
  writeFileSync(reportPath, JSON.stringify({
    run_id: runtime.runId,
    temporary_resources_removed: temporaryResourcesRemoved,
    normal_uploads_unchanged: unchanged,
    normal_parsed_unchanged: unchanged,
    differences: unchanged ? [] : [{ before: runtime.protectedSnapshot, after }],
  }, null, 2), 'utf-8')

  if (!temporaryResourcesRemoved || !unchanged) {
    throw new Error(
      `E2E isolation violation: temporary resources removed=${temporaryResourcesRemoved}; normal database/upload/parsed state changed. `
      + `before=${beforeJson} after=${afterJson}`,
    )
  }
}
