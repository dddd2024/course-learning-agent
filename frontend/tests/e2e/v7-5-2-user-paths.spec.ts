/**
 * V7.5.2 E2E: Strengthened V1.0 real user-path gating tests.
 *
 * Stronger assertions than V7.5.1 — verifies exact page counts, KP banner
 * text matching, old-material deletion, actual image element visibility,
 * and structured text mode activation for non-PDF materials.
 */
import { expect, test, type Page, type TestInfo } from '@playwright/test'
import { existsSync } from 'fs'
import { resolve } from 'path'
import { execFileSync } from 'child_process'
import { loginWithFreshUser, API_BASE, waitForMaterialProcessed, uploadMaterial } from './helpers'

const projectRoot = resolve(process.cwd(), '..')
const venvPython = resolve(projectRoot, 'backend', '.venv', 'Scripts', 'python.exe')
const pythonExe = existsSync(venvPython) ? venvPython : 'python'

function tag() {
  return `v752-${Date.now()}-${Math.floor(Math.random() * 100_000)}`
}

function generateTextPdf(path: string, pages = 3) {
  const labels = ['第一章 概述', '第二章 原理', '第三章 应用', '第四章 总结', '第五章 练习']
  const program = [
    'import fitz, sys',
    'doc = fitz.open()',
    ...labels.slice(0, pages).map((label, i) => [
      `page = doc.new_page()`,
      `page.insert_text((72, 72), '${label}', fontsize=24)`,
      `page.draw_rect(fitz.Rect(72, 120, 360, 260), color=(0, 0.2, 0.8), fill=(0.9, 0.95, 1))`,
      `page.insert_text((72, 300), '这是第${i + 1}页的正文内容，包含关键概念和定义。', fontsize=14)`,
    ].join('; ')),
    'doc.save(sys.argv[1])',
  ].join('; ')
  execFileSync(pythonExe, ['-c', program, path], { stdio: 'inherit' })
}

function generateScannedPdf(path: string) {
  // Image-only PDF: insert a raster image as the entire page content
  const program = [
    'import fitz, sys, io',
    'from PIL import Image, ImageDraw',
    'doc = fitz.open()',
    'img = Image.new("RGB", (612, 792), "white")',
    'draw = ImageDraw.Draw(img)',
    'draw.rectangle([50, 50, 562, 200], fill="#e3f2fd")',
    'draw.text((100, 100), "Scanned Document Page 1", fill="black")',
    'buf = io.BytesIO()',
    'img.save(buf, format="PNG")',
    'page = doc.new_page(width=612, height=792)',
    'page.insert_image(fitz.Rect(0, 0, 612, 792), stream=buf.getvalue())',
    'doc.save(sys.argv[1])',
  ].join('; ')
  execFileSync(pythonExe, ['-c', program, path], { stdio: 'inherit' })
}

async function createCourse(page: Page, name: string): Promise<number> {
  await page.goto('/courses')
  await page.getByRole('button', { name: '新建课程' }).first().click()
  const dialog = page.getByRole('dialog', { name: '新建课程' })
  await dialog.locator('input').first().fill(name)
  const created = page.waitForResponse(
    (r) => r.url().includes('/api/v1/courses') && r.request().method() === 'POST' && r.ok(),
  )
  await dialog.getByRole('button', { name: '确定' }).click()
  return Number((await (await created).json()).id)
}

// ── P1-T01: Upload → Parse → Preview → Q&A ─────────────────────────
test('P1-T01: upload PDF → parse → preview original page → ask AI', async ({ page, request }, testInfo) => {
  await loginWithFreshUser(page)
  const courseId = await createCourse(page, `T01 ${tag()}`)
  const fixture = testInfo.outputPath('text-fixture.pdf')
  generateTextPdf(fixture, 3)

  await page.goto(`/courses/${courseId}/materials`)
  await page.locator('input[type="file"]').setInputFiles(fixture)
  await expect(page.locator('tbody').getByText('已就绪', { exact: true })).toBeVisible({ timeout: 90_000 })

  // Navigate to learn view — should auto-select original page mode
  await page.goto(`/courses/${courseId}/learn`)
  await expect(page.locator('.page-canvas')).toBeVisible({ timeout: 30_000 })

  // Stronger: verify the actual page image element is rendered (not just the container)
  await expect(page.locator('img[alt*="原页图像"]').first()).toBeVisible({ timeout: 30_000 })

  // Stronger: verify page-sheet articles exist (at least 1)
  await expect(page.locator('article.page-sheet').first()).toBeVisible({ timeout: 30_000 })
  const sheetCount = await page.locator('article.page-sheet').count()
  expect(sheetCount).toBeGreaterThanOrEqual(1)

  // Switch to structured text mode and verify chunks
  const radioGroup = page.getByRole('radiogroup', { name: '资料展示模式' })
  if (await radioGroup.isVisible()) {
    await radioGroup.getByText('结构化文本').click()
  }
  const chunks = page.locator('.chunk-card, .doc-chunk')
  await expect(chunks.first()).toBeVisible({ timeout: 30_000 })
  // Stronger: verify at least one chunk exists with non-empty text
  expect(await chunks.count()).toBeGreaterThanOrEqual(1)
  const firstChunkText = (await chunks.first().textContent()) ?? ''
  expect(firstChunkText.trim().length).toBeGreaterThan(0)

  // Ask AI a question
  const chatInput = page.locator('textarea[placeholder*="问题"], textarea[placeholder*="提问"], input[placeholder*="问题"]')
  if (await chatInput.first().isVisible()) {
    await chatInput.first().fill('什么是概述？')
    const sendBtn = page.getByRole('button', { name: /发送|提问|问/ })
    if (await sendBtn.isVisible()) {
      const aiResponse = page.waitForResponse(
        (r) => r.url().includes('/api/v1/chat') && r.request().method() === 'POST',
        { timeout: 30_000 },
      )
      await sendBtn.click()
      const resp = await aiResponse
      expect(resp.ok()).toBeTruthy()
    }
  }
  await page.screenshot({ path: testInfo.outputPath('t01-qa.png'), fullPage: true })
})

// ── P1-T02: Knowledge point generation → jump ──────────────────────
test('P1-T02: generate knowledge points → click KP → verify focus banner', async ({ page, request }, testInfo) => {
  await loginWithFreshUser(page)
  const headers = {
    Authorization: `Bearer ${await page.evaluate(() => sessionStorage.getItem('token') || localStorage.getItem('token') || '')}`,
  }

  const courseName = `T02 ${tag()}`
  const courseRes = await request.post(`${API_BASE}/courses`, { headers, data: { name: courseName } })
  const courseId = (await courseRes.json()).id

  // Upload text material (reliable for KP generation)
  const textContent = Buffer.from(
    '操作系统课程笔记\n\n快表TLB是页表的高速缓存，用于加速虚拟地址到物理地址的转换。\n页表存储虚拟页到物理页的映射关系。\nTLB命中时无需访问内存中的页表，提升了地址转换速度。\n虚拟内存管理是操作系统的核心功能之一。\n',
    'utf-8',
  )
  const matRes = await request.post(`${API_BASE}/courses/${courseId}/materials`, {
    headers,
    multipart: { file: { name: 'os-notes.txt', mimeType: 'text/plain', buffer: textContent } },
  })
  const materialId = (await matRes.json()).id

  // Wait for parse
  await waitForMaterialProcessed(request, headers, courseId, materialId, 90_000)

  // Generate knowledge points
  const kpRes = await request.post(`${API_BASE}/courses/${courseId}/knowledge-points/generate`, { headers })
  expect(kpRes.ok()).toBeTruthy()
  const kpBody = await kpRes.json()
  expect(kpBody.knowledge_points.length).toBeGreaterThan(0)

  // Navigate to learn view with KP selected
  const kp = kpBody.knowledge_points[0]
  await page.goto(`/courses/${courseId}/learn?kp_title=${encodeURIComponent(kp.title)}&kp_summary=${encodeURIComponent(kp.summary || '')}`)

  // Verify KP focus banner appears
  const banner = page.locator('.kp-focus-banner')
  await expect(banner).toBeVisible({ timeout: 15_000 })
  // Stronger: banner text CONTAINS the KP title (not just visible)
  await expect(banner).toContainText(kp.title)

  // Stronger: verify materialPages loaded — page canvas or chunk cards visible
  const readerContent = page.locator('.page-canvas, .chunk-card, .doc-chunk')
  await expect(readerContent.first()).toBeVisible({ timeout: 30_000 })

  await page.screenshot({ path: testInfo.outputPath('t02-kp-jump.png'), fullPage: true })
})

// ── P1-T03: Delete material → re-upload → version consistency ─────
test('P1-T03: delete material → re-upload → verify new version works', async ({ page, request }, testInfo) => {
  await loginWithFreshUser(page)
  const headers = {
    Authorization: `Bearer ${await page.evaluate(() => sessionStorage.getItem('token') || localStorage.getItem('token') || '')}`,
  }

  const courseName = `T03 ${tag()}`
  const courseRes = await request.post(`${API_BASE}/courses`, { headers, data: { name: courseName } })
  const courseId = (await courseRes.json()).id

  // Upload PDF
  const fixture = testInfo.outputPath('delete-test.pdf')
  generateTextPdf(fixture, 2)
  const materialId = await uploadMaterial(request, headers, courseId, fixture, 'delete-test.pdf', 'application/pdf')
  await waitForMaterialProcessed(request, headers, courseId, materialId, 90_000)

  // Verify page assets exist
  const integrityRes = await request.get(`${API_BASE}/materials/${materialId}/image-integrity`, { headers })
  const integrity = await integrityRes.json()
  expect(integrity.expected_pages).toBeGreaterThan(0)
  expect(integrity.ready_pages).toBeGreaterThan(0)

  // Delete the material
  const delRes = await request.delete(`${API_BASE}/materials/${materialId}`, { headers })
  expect(delRes.status()).toBe(200)

  // Re-upload the same file
  const reMatRes = await request.post(`${API_BASE}/courses/${courseId}/materials`, {
    headers,
    multipart: { file: { name: 'delete-test.pdf', mimeType: 'application/pdf', buffer: require('fs').readFileSync(fixture) } },
  })
  const newMaterialId = (await reMatRes.json()).id
  await waitForMaterialProcessed(request, headers, courseId, newMaterialId, 90_000)

  // Stronger: verify new material ID is DIFFERENT from old ID
  expect(newMaterialId).not.toBe(materialId)

  // Verify new material has correct page assets
  const newIntegrityRes = await request.get(`${API_BASE}/materials/${newMaterialId}/image-integrity`, { headers })
  const newIntegrity = await newIntegrityRes.json()
  expect(newIntegrity.expected_pages).toBeGreaterThan(0)
  expect(newIntegrity.ready_pages).toBeGreaterThan(0)

  // Stronger: verify old material ID returns 404 (deletion cleaned up)
  const oldRes = await request.get(`${API_BASE}/materials/${materialId}/image-integrity`, { headers })
  expect(oldRes.status()).toBe(404)

  // Verify learn view works
  await page.goto(`/courses/${courseId}/learn`)
  await expect(page.locator('.page-canvas')).toBeVisible({ timeout: 30_000 })
  await page.screenshot({ path: testInfo.outputPath('t03-reupload.png'), fullPage: true })
})

// ── P1-T04: Repair document preview ────────────────────────────────
test('P1-T04: repair document preview via API', async ({ page, request }, testInfo) => {
  await loginWithFreshUser(page)
  const headers = {
    Authorization: `Bearer ${await page.evaluate(() => sessionStorage.getItem('token') || localStorage.getItem('token') || '')}`,
  }

  const courseName = `T04 ${tag()}`
  const courseRes = await request.post(`${API_BASE}/courses`, { headers, data: { name: courseName } })
  const courseId = (await courseRes.json()).id

  const fixture = testInfo.outputPath('repair-test.pdf')
  generateTextPdf(fixture, 2)
  const materialId = await uploadMaterial(request, headers, courseId, fixture, 'repair-test.pdf', 'application/pdf')
  await waitForMaterialProcessed(request, headers, courseId, materialId, 90_000)

  // Call rebuild endpoint
  const rebuildRes = await request.post(`${API_BASE}/materials/${materialId}/page-assets/rebuild`, { headers })
  expect(rebuildRes.ok()).toBeTruthy()
  const rebuildBody = await rebuildRes.json()
  // Stronger: exact page counts (not just > 0)
  expect(rebuildBody.expected_pages).toBe(2)
  expect(rebuildBody.ready_pages).toBe(2)
  expect(rebuildBody.status).toBe('ready')

  // Verify in learn view
  await page.goto(`/courses/${courseId}/learn`)
  await expect(page.locator('.page-canvas')).toBeVisible({ timeout: 30_000 })
  // Stronger: verify actual page image element rendered (not just canvas container)
  await expect(page.locator('img[alt*="原页图像"]').first()).toBeVisible({ timeout: 30_000 })
  await page.screenshot({ path: testInfo.outputPath('t04-repair.png'), fullPage: true })
})

// ── P1-T05: Non-PDF material defaults to structured text ───────────
test('P1-T05: non-PDF material defaults to structured text mode', async ({ page, request }, testInfo) => {
  await loginWithFreshUser(page)
  const headers = {
    Authorization: `Bearer ${await page.evaluate(() => sessionStorage.getItem('token') || localStorage.getItem('token') || '')}`,
  }

  const courseName = `T05 ${tag()}`
  const courseRes = await request.post(`${API_BASE}/courses`, { headers, data: { name: courseName } })
  const courseId = (await courseRes.json()).id

  // Upload a TXT file
  const textContent = Buffer.from(
    '# Markdown 测试文档\n\n## 第一节\n\n这是正文内容，用于测试非PDF资料的阅读模式。\n\n## 第二节\n\n更多内容。\n',
    'utf-8',
  )
  const matRes = await request.post(`${API_BASE}/courses/${courseId}/materials`, {
    headers,
    multipart: { file: { name: 'notes.md', mimeType: 'text/markdown', buffer: textContent } },
  })
  const materialId = (await matRes.json()).id
  await waitForMaterialProcessed(request, headers, courseId, materialId, 90_000)

  // Navigate to learn view
  await page.goto(`/courses/${courseId}/learn`)

  // Page canvas should NOT be visible for non-PDF
  await expect(page.locator('.page-canvas')).not.toBeVisible({ timeout: 10_000 })

  // Stronger: verify structured text mode is active — chunk elements exist (at least 1)
  const chunks = page.locator('.chunk-card, .doc-chunk')
  await expect(chunks.first()).toBeVisible({ timeout: 30_000 })
  expect(await chunks.count()).toBeGreaterThanOrEqual(1)

  // If radio group visible, verify "结构化文本" option exists
  const radioGroup = page.getByRole('radiogroup', { name: '资料展示模式' })
  if (await radioGroup.isVisible()) {
    await expect(radioGroup.getByText('结构化文本')).toBeVisible()
  }

  await page.screenshot({ path: testInfo.outputPath('t05-non-pdf.png'), fullPage: true })
})

// ── P1-T06: Scanned/image-only PDF shows original page preview ─────
test('P1-T06: scanned PDF shows original page preview without false alert', async ({ page, request }, testInfo) => {
  await loginWithFreshUser(page)
  const headers = {
    Authorization: `Bearer ${await page.evaluate(() => sessionStorage.getItem('token') || localStorage.getItem('token') || '')}`,
  }

  const courseName = `T06 ${tag()}`
  const courseRes = await request.post(`${API_BASE}/courses`, { headers, data: { name: courseName } })
  const courseId = (await courseRes.json()).id

  const fixture = testInfo.outputPath('scanned.pdf')
  generateScannedPdf(fixture)

  const materialId = await uploadMaterial(request, headers, courseId, fixture, 'scanned.pdf', 'application/pdf')
  const finalStatus = await waitForMaterialProcessed(request, headers, courseId, materialId, 90_000)

  // Even if chunks are empty (scanned PDF), page assets should exist
  await page.goto(`/courses/${courseId}/learn`)

  // Page canvas should be visible (page assets exist even without text chunks)
  await expect(page.locator('.page-canvas')).toBeVisible({ timeout: 30_000 })

  // Stronger: verify actual page image element rendered
  await expect(page.locator('img[alt*="原页图像"]').first()).toBeVisible({ timeout: 30_000 })

  // Should NOT show a blocking "document unreadable" alert
  // (non-blocking info banner is acceptable)
  const blockingAlert = page.locator('.image-error-banner .el-alert--warning')
  await expect(blockingAlert).not.toBeVisible({ timeout: 5_000 })

  await page.screenshot({ path: testInfo.outputPath('t06-scanned.png'), fullPage: true })
})
