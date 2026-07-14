import { mkdirSync, writeFileSync } from 'fs'
import {
  assertIsolatedPath,
  backendPort,
  e2eArtifactDir,
  e2eDatabasePath,
  e2eDatabaseUrl,
  e2eManifestPath,
  e2eRunId,
  e2eRunRoot,
  e2eUploadDir,
  frontendPort,
  normalUploadDir,
  snapshotDirectory,
  workerPort,
} from './e2e-runtime'

export default async function globalSetup() {
  assertIsolatedPath(e2eDatabasePath)
  assertIsolatedPath(e2eUploadDir)
  mkdirSync(e2eRunRoot, { recursive: true })
  mkdirSync(e2eUploadDir, { recursive: true })
  mkdirSync(e2eArtifactDir, { recursive: true })

  const manifest = {
    run_id: e2eRunId,
    run_root: e2eRunRoot,
    database_path: e2eDatabasePath,
    database_url: e2eDatabaseUrl,
    upload_dir: e2eUploadDir,
    normal_upload_dir: normalUploadDir,
    ports: {
      backend: backendPort,
      worker: workerPort,
      frontend: frontendPort,
    },
    normal_uploads_before: snapshotDirectory(normalUploadDir),
    created_at: new Date().toISOString(),
  }

  writeFileSync(e2eManifestPath, JSON.stringify(manifest, null, 2), 'utf-8')
  process.env.E2E_RUNTIME_MANIFEST = e2eManifestPath
}
