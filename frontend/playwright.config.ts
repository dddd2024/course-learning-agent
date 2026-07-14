import { defineConfig, devices } from '@playwright/test'
import { existsSync } from 'fs'
import { dirname, resolve } from 'path'
import { fileURLToPath } from 'url'

import { createE2ERuntime } from './tests/e2e/e2e-runtime'

/**
 * V7.5.2-04 Playwright configuration.
 *
 * Every invocation receives a unique database, upload directory, parsed
 * directory and three checked local ports.  The API and parse worker receive
 * the same explicit E2E mirrors, so backend startup fails before touching disk
 * if one process drifts to a normal development path.
 */
const __dirname = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(__dirname, '..')
const runtime = await createE2ERuntime(repoRoot)

const venvPython = resolve(repoRoot, 'backend', '.venv', 'Scripts', 'python.exe')
const pythonExe = existsSync(venvPython) ? venvPython : 'python'

const sharedBackendEnv = {
  LLM_PROVIDER: 'mock',
  DATABASE_URL: runtime.databaseUrl,
  UPLOAD_DIR: runtime.uploadDir,
  PARSED_DIR: runtime.parsedDir,
  E2E_MODE: 'true',
  E2E_RUN_ID: runtime.runId,
  E2E_DATABASE_URL: runtime.databaseUrl,
  E2E_UPLOAD_DIR: runtime.uploadDir,
  E2E_PARSED_DIR: runtime.parsedDir,
}

export default defineConfig({
  testDir: './tests/e2e',
  globalSetup: './tests/e2e/global-setup.ts',
  globalTeardown: './tests/e2e/global-teardown.ts',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [
    ['html', { outputFolder: 'playwright-report' }],
    ['json', { outputFile: process.env.PLAYWRIGHT_JSON_OUTPUT ?? 'playwright-results.json' }],
    ['list'],
  ],
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  use: {
    baseURL: `http://127.0.0.1:${runtime.frontendPort}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || 'test-results',
  webServer: [
    {
      command: `cd ../backend && ${pythonExe} -c "from app.models import Base; from app.core.database import engine; Base.metadata.create_all(engine); print('DB initialized')" && ${pythonExe} ../scripts/migrate.py && ${pythonExe} -m uvicorn app.main:app --host 127.0.0.1 --port ${runtime.backendPort}`,
      env: {
        ...sharedBackendEnv,
        CORS_ORIGINS: `http://127.0.0.1:${runtime.frontendPort}`,
      },
      url: `http://127.0.0.1:${runtime.backendPort}/api/v1/health`,
      reuseExistingServer: false,
      timeout: 90_000,
    },
    {
      command: `cd .. && ${pythonExe} scripts/start_parse_worker_with_health.py`,
      env: {
        ...sharedBackendEnv,
        PARSE_WORKER_HEALTH_PORT: String(runtime.workerPort),
      },
      url: `http://127.0.0.1:${runtime.workerPort}/`,
      reuseExistingServer: false,
      timeout: 90_000,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${runtime.frontendPort} --strictPort`,
      env: {
        E2E_BACKEND_PORT: String(runtime.backendPort),
        E2E_FRONTEND_PORT: String(runtime.frontendPort),
      },
      url: `http://127.0.0.1:${runtime.frontendPort}`,
      reuseExistingServer: false,
      timeout: 90_000,
    },
  ],
})
