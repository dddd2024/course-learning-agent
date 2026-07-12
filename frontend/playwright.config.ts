import { defineConfig, devices } from '@playwright/test'
import { existsSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

/**
 * Playwright E2E configuration.
 *
 * Starts the backend (port 8000), parse worker (port 8001), and
 * frontend (port 5173) dev servers, then runs the E2E test suite
 * against the Vite dev server.
 */

const __dirname = dirname(fileURLToPath(import.meta.url))

// Use the backend virtual-env Python when available (local dev on
// Windows).  On CI (Ubuntu) packages are installed globally so
// ``python`` resolves correctly.
const venvPython = resolve(__dirname, '..', 'backend', '.venv', 'Scripts', 'python.exe')
const pythonExe = existsSync(venvPython) ? venvPython : 'python'

// Use a single shared SQLite database so the backend server and the
// parse worker (which run from different working directories) see the
// same data.  In CI the DATABASE_URL env var is already set by the
// workflow, so we only set a default for local development.
const defaultDbUrl = `sqlite:///${resolve(__dirname, '..', 'e2e-test.db').replace(/\\/g, '/')}`
const dbUrl = process.env.DATABASE_URL || defaultDbUrl

// Use an absolute UPLOAD_DIR so the backend (CWD=backend/) and the
// parse worker (CWD=project-root) resolve to the same directory.
// Without this, the relative default "../storage/uploads" resolves
// to different absolute paths for each process.
const uploadDir = resolve(__dirname, '..', 'storage', 'uploads').replace(/\\/g, '/')
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
    baseURL: 'http://127.0.0.1:5173',
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
  outputDir: 'test-results',
  webServer: [
    {
      command: `cd ../backend && ${pythonExe} -c "from app.models import Base; from app.core.database import engine; Base.metadata.create_all(engine); print('DB initialized')" && ${pythonExe} ../scripts/migrate.py && ${pythonExe} -m uvicorn app.main:app --host 127.0.0.1 --port 8000`,
      env: {
        LLM_PROVIDER: 'mock',
        DATABASE_URL: dbUrl,
        UPLOAD_DIR: uploadDir,
      },
      url: 'http://127.0.0.1:8000/docs',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: `cd .. && ${pythonExe} scripts/start_parse_worker_with_health.py`,
      env: {
        LLM_PROVIDER: 'mock',
        DATABASE_URL: dbUrl,
        UPLOAD_DIR: uploadDir,
      },
      url: 'http://127.0.0.1:8001/',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: 'npm run dev',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
})
