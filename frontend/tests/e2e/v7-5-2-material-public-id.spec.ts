/** Stable public material URLs must survive the legacy numeric route boundary. */
import { expect, test, type Page, type APIRequestContext } from '@playwright/test'
import { existsSync } from 'fs'
import { basename, resolve } from 'path'
import { execFileSync } from 'child_process'
import { API_BASE, loginWithFreshUser, uploadMaterial, waitForMaterialReadyForReading } from './helpers'

const root = resolve(process.cwd(), '..')
const python = existsSync(resolve(root, 'backend', '.venv', 'Scripts', 'python.exe'))
  ? resolve(root, 'backend', '.venv', 'Scripts', 'python.exe') : 'python'

function makePdf(path: string) {
  execFileSync(python, ['-c', "import fitz,sys;d=fitz.open();p=d.new_page();p.insert_text((72,72),'public identity material',fontsize=20);d.save(sys.argv[1])", path])
}

async function createCourse(page: Page) {
  await page.goto('/courses')
  await page.getByRole('button', { name: '新建课程' }).first().click()
  const dialog = page.getByRole('dialog', { name: '新建课程' })
  await dialog.locator('input').first().fill(`public-${Date.now()}`)
  const response = page.waitForResponse(r => r.url().includes('/api/v1/courses') && r.request().method() === 'POST')
  await dialog.getByRole('button', { name: '确定' }).click()
  return Number((await (await response).json()).id)
}

async function auth(page: Page) { return { Authorization: `Bearer ${await page.evaluate(() => sessionStorage.getItem('token') || '')}` } }

async function uploadReady(page: Page, request: APIRequestContext, courseId: number, file: string) {
  const headers = await auth(page)
  const id = await uploadMaterial(request, headers, courseId, file, basename(file), 'application/pdf')
  expect((await request.post(`${API_BASE}/materials/${id}/parse`, { headers })).ok()).toBeTruthy()
  await waitForMaterialReadyForReading(request, headers, id, 90_000)
  const list = await request.get(`${API_BASE}/courses/${courseId}/materials`, { headers })
  const material = (await list.json()).items.find((item: { id: number }) => item.id === id)
  expect(material?.public_id).toMatch(/^[0-9a-f-]{36}$/i)
  return { headers, id, publicId: material.public_id as string }
}

test('P1-ID01: public material URL and public page/readiness APIs render a real document', async ({ page, request }, info) => {
  await loginWithFreshUser(page)
  const courseId = await createCourse(page)
  const file = info.outputPath('public.pdf'); makePdf(file)
  const material = await uploadReady(page, request, courseId, file)
  const [pages, readiness] = await Promise.all([
    request.get(`${API_BASE}/materials/${material.publicId}/pages`, { headers: material.headers }),
    request.get(`${API_BASE}/materials/${material.publicId}/readiness`, { headers: material.headers }),
  ])
  expect(pages.ok()).toBeTruthy(); expect(readiness.ok()).toBeTruthy()
  expect((await pages.json()).items).toHaveLength(1)
  expect((await readiness.json()).effective_page_count).toBe(1)
  await page.goto(`/courses/${courseId}/learn?material=${material.publicId}`)
  await expect(page).toHaveURL(new RegExp(`material=${material.publicId}`))
  await expect(page.locator('img[alt*="原页图像"]')).toHaveCount(1, { timeout: 30_000 })
  expect(material.id).toBeGreaterThan(0)
})

test('P1-ID02: numeric legacy URLs load and normalize to public URLs', async ({ page, request }, info) => {
  await loginWithFreshUser(page)
  const courseId = await createCourse(page)
  const file = info.outputPath('legacy-id.pdf'); makePdf(file)
  const material = await uploadReady(page, request, courseId, file)
  await page.goto(`/courses/${courseId}/learn?material_id=${material.id}`)
  await expect(page.locator('img[alt*="原页图像"]')).toHaveCount(1, { timeout: 30_000 })
  await expect(page).toHaveURL(new RegExp(`material=${material.publicId}`))
  await expect(page).not.toHaveURL(/material_id=/)
})

test('P1-ID03: deleted public identity never resolves to a replacement material', async ({ page, request }, info) => {
  await loginWithFreshUser(page)
  const courseId = await createCourse(page); const file = info.outputPath('deleted.pdf'); makePdf(file)
  const first = await uploadReady(page, request, courseId, file)
  expect((await request.delete(`${API_BASE}/materials/${first.publicId}`, { headers: first.headers })).status()).toBe(204)
  const second = await uploadReady(page, request, courseId, file)
  expect(second.publicId).not.toBe(first.publicId)
  for (const path of ['readiness', 'pages']) {
    expect((await request.get(`${API_BASE}/materials/${first.publicId}/${path}`, { headers: first.headers })).status()).toBe(404)
  }
})
