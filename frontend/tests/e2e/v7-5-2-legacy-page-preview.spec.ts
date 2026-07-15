/** Legacy original-page preview regression coverage (AUDIT-R1-07). */
import { expect, test, type Page, type APIRequestContext } from '@playwright/test'
import { existsSync, readFileSync } from 'fs'
import { basename, resolve } from 'path'
import { execFileSync } from 'child_process'
import { API_BASE, loginWithFreshUser, uploadMaterial, waitForMaterialReadyForReading } from './helpers'

const root = resolve(process.cwd(), '..')
const python = existsSync(resolve(root, 'backend', '.venv', 'Scripts', 'python.exe'))
  ? resolve(root, 'backend', '.venv', 'Scripts', 'python.exe') : 'python'

function makePdf(path: string, pages = 3) {
  const program = [
    'import fitz,sys', 'd=fitz.open()',
    ...Array.from({ length: pages }, (_, i) => `p=d.new_page();p.insert_text((72,72),'legacy page ${i + 1}',fontsize=20)`),
    'd.save(sys.argv[1])',
  ].join(';')
  execFileSync(python, ['-c', program, path])
}
export function sqlitePathFromUrl(url: string) {
  const match = /^sqlite:\/\/(?:\/)?(.+)$/.exec(url)
  if (!match) throw new Error(`E2E_DATABASE_URL must be a SQLite URL, received: ${url || '(empty)'}`)
  return decodeURIComponent(match[1])
}
function databasePath() { return sqlitePathFromUrl(process.env.E2E_DATABASE_URL || '') }
function sql(statement: string, ...args: string[]) {
  execFileSync(python, ['-c', 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute(sys.argv[2],tuple(sys.argv[3:])); c.commit(); print(c.execute("select changes()").fetchone()[0])', databasePath(), statement, ...args])
}
async function course(page: Page) {
  await page.goto('/courses'); await page.getByRole('button', { name: '新建课程' }).first().click()
  const dialog = page.getByRole('dialog', { name: '新建课程' }); await dialog.locator('input').first().fill(`legacy-${Date.now()}`)
  const response = page.waitForResponse(r => r.url().includes('/api/v1/courses') && r.request().method() === 'POST')
  await dialog.getByRole('button', { name: '确定' }).click(); return Number((await (await response).json()).id)
}
async function headers(page: Page) { return { Authorization: `Bearer ${await page.evaluate(() => sessionStorage.getItem('token') || '')}` } }
async function uploadReady(page: Page, request: APIRequestContext, courseId: number, file: string) {
  const auth = await headers(page); const materialId = await uploadMaterial(request, auth, courseId, file, basename(file), 'application/pdf')
  expect((await request.post(`${API_BASE}/materials/${materialId}/parse`, { headers: auth })).ok()).toBeTruthy()
  await waitForMaterialReadyForReading(request, auth, materialId, 90_000); return { auth, materialId }
}

test('P0-L01: assets without MaterialPage still render every original page', async ({ page, request }, info) => {
  await loginWithFreshUser(page); const courseId = await course(page); const file = info.outputPath('legacy.pdf'); makePdf(file, 3)
  const { auth, materialId } = await uploadReady(page, request, courseId, file)
  sql('DELETE FROM material_pages WHERE material_id=?', String(materialId))
  const [catalog, readiness] = await Promise.all([
    request.get(`${API_BASE}/materials/${materialId}/pages`, { headers: auth }), request.get(`${API_BASE}/materials/${materialId}/readiness`, { headers: auth }),
  ])
  expect((await catalog.json()).items).toHaveLength(3); expect((await readiness.json()).effective_page_count).toBe(3)
  await page.goto(`/courses/${courseId}/learn?material_id=${materialId}`)
  await expect(page.locator('img[alt*="原页图像"]')).toHaveCount(3, { timeout: 30_000 })
  const dimensions = await page.locator('img[alt*="原页图像"]').evaluateAll((images) => images.map((image) => ({ width: image.naturalWidth, height: image.naturalHeight })))
  expect(dimensions).toHaveLength(3)
  expect(dimensions.every(({ width, height }) => width > 0 && height > 0)).toBeTruthy()
  expect(await page.locator('.page-empty').count()).toBe(0)
})

test('P0-L02B: actual backend backfill failure keeps the synthetic reader readable', async ({ page, request }, info) => {
  await loginWithFreshUser(page); const courseId = await course(page); const file = info.outputPath('repair.pdf'); makePdf(file, 2)
  const { auth, materialId } = await uploadReady(page, request, courseId, file)
  sql('DELETE FROM material_pages WHERE material_id=?', String(materialId))
  await page.goto(`/courses/${courseId}/learn?material_id=${materialId}`)
  const repairButton = page.getByTestId('legacy-page-catalog-repair').getByRole('button', { name: '修复文档预览' })
  await expect(repairButton).toBeVisible({ timeout: 30_000 })
  const rebuildUrl = `**/api/v1/materials/${materialId}/page-assets/rebuild`
  await page.route(rebuildUrl, async (route) => route.continue({
    headers: { ...route.request().headers(), 'x-e2e-inject-page-backfill-failure': 'true' },
  }))
  const failedRebuild = page.waitForResponse((response) => response.url().includes(`/materials/${materialId}/page-assets/rebuild`) && response.request().method() === 'POST')
  await repairButton.click()
  const partial = await (await failedRebuild).json()
  expect(partial.status).toBe('readable_but_not_repaired')
  expect(partial.error_code).toBe('PAGE_CATALOG_BACKFILL_FAILED')
  expect(partial.page_catalog_backfill.remaining_synthetic_page_numbers).toEqual([1, 2])
  await expect(page.getByText('当前原页仍可阅读，但页面目录持久化失败。下次启动可能需要再次修复。')).toBeVisible()
  await expect(page.locator('img[alt*="原页图像"]')).toHaveCount(2)
  await expect(repairButton).toBeEnabled()
  await page.unroute(rebuildUrl)
  const repaired = page.waitForResponse((response) => response.url().includes(`/materials/${materialId}/page-assets/rebuild`) && response.request().method() === 'POST')
  await repairButton.click(); expect((await repaired).ok()).toBeTruthy()
  await page.reload()
  const catalog = await request.get(`${API_BASE}/materials/${materialId}/pages`, { headers: auth })
  expect((await catalog.json()).synthetic_page_numbers).toEqual([])
  await expect(page.locator('img[alt*="原页图像"]')).toHaveCount(2, { timeout: 30_000 })
})

test('P0-L02C: page repair success reports independent image reextract failure', async ({ page, request }, info) => {
  await loginWithFreshUser(page); const courseId = await course(page); const file = info.outputPath('reextract.pdf'); makePdf(file, 2)
  const { auth, materialId } = await uploadReady(page, request, courseId, file)
  sql('DELETE FROM material_pages WHERE material_id=?', String(materialId))
  await page.goto(`/courses/${courseId}/learn?material_id=${materialId}`)
  const repairButton = page.getByTestId('legacy-page-catalog-repair').getByRole('button', { name: '修复文档预览' })
  await expect(repairButton).toBeVisible({ timeout: 30_000 })
  const imageUrl = `**/api/v1/materials/${materialId}/images/reextract`
  await page.route(imageUrl, route => route.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"injected image failure"}' }))
  await repairButton.click()
  await expect(page.getByText('原页已修复，但独立图片提取失败。')).toBeVisible()
  const catalog = await request.get(`${API_BASE}/materials/${materialId}/pages`, { headers: auth })
  expect((await catalog.json()).synthetic_page_numbers).toEqual([])
  await expect(page.locator('img[alt*="原页图像"]')).toHaveCount(2)
})

test('P1-L03: text PDF with removed chunks keeps complete original pages readable', async ({ page, request }, info) => {
  await loginWithFreshUser(page); const courseId = await course(page); const file = info.outputPath('text.pdf'); makePdf(file, 2)
  const { auth, materialId } = await uploadReady(page, request, courseId, file)
  sql('DELETE FROM material_chunks WHERE material_id=?', String(materialId))
  const response = await request.get(`${API_BASE}/materials/${materialId}/readiness`, { headers: auth })
  const readiness = await response.json()
  expect(readiness.document_mode).toBe('unexpected_empty_text_pdf')
  expect(readiness.reader.usable).toBe(true)
  expect(readiness.reader.available_modes).toContain('page')
  expect(readiness.assistant.usable).toBe(false)
  expect(readiness.blocking_reasons).not.toContain('unexpected_empty_text_extraction')
})

test('P2-L04: changing to a distinct large document revokes prior page Blob URLs', async ({ page, request }, info) => {
  await page.addInitScript(() => {
    const original = URL.revokeObjectURL.bind(URL)
    URL.revokeObjectURL = (url: string) => {
      sessionStorage.setItem('__revokedUrlCount', String(Number(sessionStorage.getItem('__revokedUrlCount') || 0) + 1))
      original(url)
    }
  })
  await loginWithFreshUser(page); const courseId = await course(page)
  const one = info.outputPath('one.pdf'); const two = info.outputPath('two.pdf'); makePdf(one, 4); makePdf(two, 4)
  const first = await uploadReady(page, request, courseId, one); await uploadReady(page, request, courseId, two)
  await page.goto(`/courses/${courseId}/learn?material_id=${first.materialId}`)
  await expect(page.locator('img[alt*="原页图像"]')).toHaveCount(4, { timeout: 30_000 })
  // Change the in-page material selector so the component watcher releases
  // URLs before loading a second page catalogue.
  await page.locator('.material-select').click()
  await page.locator('.el-select-dropdown__item').filter({ hasText: 'two.pdf' }).click()
  await expect(page.locator('img[alt*="原页图像"]')).toHaveCount(4, { timeout: 30_000 })
  await expect(page.locator('.material-select')).toContainText('two.pdf')
  expect(await page.evaluate(() => Number(sessionStorage.getItem('__revokedUrlCount') || 0))).toBeGreaterThan(0)
})
