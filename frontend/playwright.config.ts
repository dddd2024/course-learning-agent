import { defineConfig, devices } from '@playwright/test'
import { existsSync, rmSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

/**
 * Playwright E2E configuration.
 *
 * Starts the backend (port 8000), parse worker (port 8001), and
 * frontend (port 5173) dev servers, then runs the E2E test suite
 * against the Vite dev server.
 *
 * V7.5.2-04: Forces complete environment isolation — dedicated E2E
 * database, dedicated upload directory, and CLEAN_E2E_DB to drop and
 * recreate tables before each run.
 */

const __dirname = dirname(fileURLToPath(import.meta.url))

const venvPython = resolve(__dirname, '..', 'backend', '.venv', 'Scripts', 'python.exe')
const pythonExe = existsSync(venvPython) ? venvPython : 'python'

// V7.5.2-04: Dedicated E2E database, separate from dev/prod.
const e2eDbPath = resolve(__dirname, '..', 'e2e-test.db')
const defaultDbUrl = `sqlite:///${e2eDbPath.replace(/\\/g, '/')}`
const dbUrl = process.env.DATABASE_URL || defaultDbUrl
const backendPort = Number(process.env.E2E_BACKEND_PORT || '8000')
const workerPort = Number(process.env.E2E_WORKER_PORT || '8001')
const frontendPort = Number(process.env.E2E_FRONTEND_PORT || '5173')

// V7.5.2-04: Isolated upload directory.
const uploadDir = resolve(__dirname, '..', 'storage', 'e2e-uploads').replace(/\\/g, '/')

// V7.5.2-04: Delete stale E2E database before starting.
try { rmSync(e2eDbPath, { force: true }) } catch { /* ignore */ }
try { rmSync(uploadDir, { recursive: true, force: true }) } catch { /* ignore */ }

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : 1,
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
        LLM_PROVIDER: 'mock',
        DATABASE_URL: dbUrl,
        UPLOAD_DIR: uploadDir,
        E2E_MODE: 'true',
        CLEAN_E2E_DB: 'true',
      },
      url: `http://127.0.0.1:${backendPort}/docs`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: `cd .. && ${pythonExe} scripts/start_parse_worker_with_health.py`,
      env: {
        LLM_PROVIDER: 'mock',
        DATABASE_URL: dbUrl,
        UPLOAD_DIR: uploadDir,
        PARSE_WORKER_HEALTH_PORT: String(workerPort),
        E2E_MODE: 'true',
      },
      url: `http://127.0.0.1:${workerPort}/`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: `npm run dev -- --port ${frontendPort}`,
      url: `http://127.0.0.1:${frontendPort}`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
})
