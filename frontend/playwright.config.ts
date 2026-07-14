import { defineConfig, devices } from '@playwright/test'
import { existsSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'
import {
  backendPort,
  e2eDatabaseUrl,
  e2eRunId,
  e2eRunRoot,
  e2eUploadDir,
  frontendPort,
  workerPort,
} from './tests/e2e/e2e-runtime'

const __dirname = dirname(fileURLToPath(import.meta.url))
const venvPython = resolve(__dirname, '..', 'backend', '.venv', 'Scripts', 'python.exe')
const pythonExe = existsSync(venvPython) ? venvPython : 'python'

const sharedBackendEnv = {
  LLM_PROVIDER: 'mock',
  DATABASE_URL: e2eDatabaseUrl,
  E2E_DATABASE_URL: e2eDatabaseUrl,
  UPLOAD_DIR: e2eUploadDir,
  E2E_UPLOAD_DIR: e2eUploadDir,
  ENVIRONMENT: 'e2e',
  E2E_RUN_ID: e2eRunId,
  E2E_RUN_ROOT: e2eRunRoot,
}

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  forbidOnly: true,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [
    ['html', { outputFolder: 'playwright-report' }],
    ['json', { outputFile: process.env.PLAYWRIGHT_JSON_OUTPUT ?? 'playwright-results.json' }],
    ['list'],
  ],
  globalSetup: './tests/e2e/global-setup.ts',
  globalTeardown: './tests/e2e/global-teardown.ts',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: `http://127.0.0.1:${frontendPort}`,
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
      command: `cd ../backend && ${pythonExe} -c "from app.models import Base; from app.core.database import engine; Base.metadata.create_all(engine); print('DB initialized')" && ${pythonExe} ../scripts/migrate.py && ${pythonExe} -m uvicorn app.main:app --host 127.0.0.1 --port ${backendPort}`,
      env: {
        ...sharedBackendEnv,
        CLEAN_E2E_DB: 'true',
      },
      url: `http://127.0.0.1:${backendPort}/docs`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `cd .. && ${pythonExe} scripts/start_parse_worker_with_health.py`,
      env: {
        ...sharedBackendEnv,
        PARSE_WORKER_HEALTH_PORT: String(workerPort),
      },
      url: `http://127.0.0.1:${workerPort}/`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npm run dev -- --port ${frontendPort}`,
      env: {
        E2E_RUN_ID: e2eRunId,
        E2E_FRONTEND_PORT: String(frontendPort),
        E2E_BACKEND_PORT: String(backendPort),
      },
      url: `http://127.0.0.1:${frontendPort}`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
