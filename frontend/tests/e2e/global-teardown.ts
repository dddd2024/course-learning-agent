import { captureProtectedSnapshot, cleanupRuntime, readRuntimeManifest } from './e2e-runtime'

export default async function globalTeardown(): Promise<void> {
  const runtime = readRuntimeManifest()
  const after = captureProtectedSnapshot(runtime.protectedPaths)
  const beforeJson = JSON.stringify(runtime.protectedSnapshot)
  const afterJson = JSON.stringify(after)

  cleanupRuntime(runtime)

  if (beforeJson !== afterJson) {
    throw new Error(
      'E2E isolation violation: normal database/upload/parsed state changed. '
      + `before=${beforeJson} after=${afterJson}`,
    )
  }
}
