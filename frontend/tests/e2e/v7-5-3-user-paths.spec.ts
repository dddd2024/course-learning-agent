import { expect, test, type APIRequestContext, type Page, type TestInfo } from '@playwright/test'
import { existsSync } from 'fs'
import { execFileSync } from 'child_process'
import { resolve } from 'path'
import {
  API_BASE,
  createCourse,
  registerUniqueUser,
  uploadBuffer,
  uploadMaterial,
  waitForMaterialProcessed,
} from './helpers'

const projectRoot = resolve(process.cwd(), '..')
const venvPython = resolve(projectRoot, 'backend', '.venv', 'Scripts', 'python.exe')
const pythonExe = existsSync(venvPython) ? venvPython : 'python'
const fixtureHelper = resolve(projectRoot, 'scripts', 'e2e_v7_5_3_fixture.py')

function unique(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 100_000)}`
}

function generateEmbeddedPdf(path: string, pages: number, label: string) {
  const program = [
    'import fitz,sys,io',
    'from PIL import Image,ImageDraw',
    'path=sys.argv[1]; pages=int(sys.argv[2]); label=sys.argv[3]',
    'doc=fitz.open()',
    'for i in range(pages):',
    ' p=doc.new_page()',
    ' p.insert_textbox(fitz.Rect(60,50,540,260), f"{label} page {i+1}\\nThis page explains a distinct course concept with definitions examples and practical details.\\nThe content is intentionally long enough to produce a semantic chunk for retrieval and citations.", fontsize=14)',
    ' img=Image.new("RGB",(320,180),(220-i*10,235,255))',
    ' d=ImageDraw.Draw(img); d.rectangle((20,20,300,160),outline="navy",width=5); d.text((45,75),f"{label}-{i+1}",fill="black")',
    ' b=io.BytesIO(); img.save(b,format="PNG")',
    ' p.insert_image(fitz.Rect(100,300,420,480),stream=b.getvalue())',
    'doc.save(path); doc.close()',
  ].join('\n')
  execFileSync(pythonExe, ['-c', program, path, String(pages), label], { stdio: 'inherit' })
}

function generateScannedPdf(path: string) {
  const program = [
    'import fitz,sys,io',
    'from PIL import Image,ImageDraw',
    'img=Image.new("RGB",(800,1000),"white")',
    'd=ImageDraw.Draw(img); d.rectangle((40,40,760,960),outline="black",width=5); d.text((120,160),"SCANNED PAGE WITHOUT TEXT LAYER",fill="black")',
    'b=io.BytesIO(); img.save(b,format="PNG")',
    'doc=fitz.open(); p=doc.new_page(width=800,height=1000); p.insert_image(p.rect,stream=b.getvalue()); doc.save(sys.argv[1]); doc.close()',
  ].join('\n')
  execFileSync(pythonExe, ['-c', program, path], { stdio: 'inherit' })
}

function runFixture(command: string, ...args: string[]) {
  const stdout = execFileSync(pythonExe, [fixtureHelper, command, ...args], {
    cwd: projectRoot,
    env: process.env,
    encoding: 'utf-8',
  })
  const lines = stdout.trim().split(/\r?\n/)
  return JSON.parse(lines[lines.length - 1])
}

async function readyPdf(
  request: APIRequestContext,
  headers: Record<string, string>,
  courseId: number,
  path: string,
  filename: string,
) {
  const id = await uploadMaterial(request, headers, courseId, path, filename, 'application/pdf')
  expect(await waitForMaterialProcessed(request, headers, courseId, id)).toBe('ready')
  return id
}

async function actualImageIsDecoded(page: Page) {
  const image = page.locator('img[alt*="原页图像"]').first()
  await expect(image).toBeVisible({ timeout: 30_000 })
  await expect.poll(async () => image.evaluate((node: HTMLImageElement) => ({
    width: node.naturalWidth,
    height: node.naturalHeight,
  })), { timeout: 30_000 }).toEqual(expect.objectContaining({ width: expect.any(Number), height: expect.any(Number) }))
  const dimensions = await image.evaluate((node: HTMLImageElement) => [node.naturalWidth, node.naturalHeight])
  expect(dimensions[0]).toBeGreaterThan(0)
  expect(dimensions[1]).toBeGreaterThan(0)
}

// T01: a real PDF must support original-page reading, structured chunks, and cited Q&A.
test('T01 PDF upload → original page → structured text → cited Q&A', async ({ page, request }, testInfo) => {
  const { headers } = await registerUniqueUser(page, request, 'v753-t01')
  const courseId = await createCourse(request, headers, unique('T01'))
  const fixture = testInfo.outputPath('learning.pdf')
  generateEmbeddedPdf(fixture, 2, 'operating-system-memory')
  await readyPdf(request, headers, courseId, fixture, 'learning.pdf')

  await page.goto(`/courses/${courseId}/learn`)
  await expect(page.locator('.page-canvas')).toBeVisible({ timeout: 30_000 })
  await actualImageIsDecoded(page)

  const cleanRadio = page.getByRole('radio', { name: '结构化文本' })
  await expect(cleanRadio).toBeVisible()
  await cleanRadio.click()
  await expect(cleanRadio).toBeChecked()
  const chunk = page.locator('.doc-chunk').first()
  await expect(chunk).toBeVisible({ timeout: 30_000 })
  expect(((await chunk.textContent()) || '').trim().length).toBeGreaterThan(20)

  const question = page.getByPlaceholder('输入问题，回车发送')
  await expect(question).toBeVisible()
  await question.fill('What concept does this material explain?')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  const answer = page.locator('.ai-msg-bubble.assistant').last()
  await expect(answer).toBeVisible({ timeout: 30_000 })
  expect(((await answer.textContent()) || '').trim().length).toBeGreaterThan(0)
  await expect(page.locator('.ai-cite-tag').first()).toBeVisible({ timeout: 30_000 })
})

// T02: source chunk IDs from multiple materials must select the best-matching material.
test('T02 knowledge-point source IDs select the best material and load its page', async ({ page, request }, testInfo) => {
  const { headers } = await registerUniqueUser(page, request, 'v753-t02')
  const courseId = await createCourse(request, headers, unique('T02'))
  const firstFixture = testInfo.outputPath('first.pdf')
  const bestFixture = testInfo.outputPath('best.pdf')
  generateEmbeddedPdf(firstFixture, 1, 'unrelated-material')
  generateEmbeddedPdf(bestFixture, 2, 'target-knowledge-material')
  const firstId = await readyPdf(request, headers, courseId, firstFixture, 'first.pdf')
  const bestId = await readyPdf(request, headers, courseId, bestFixture, 'best.pdf')

  const firstChunks = await (await request.get(`${API_BASE}/materials/${firstId}/chunks?page=1&page_size=100`, { headers })).json()
  const bestChunks = await (await request.get(`${API_BASE}/materials/${bestId}/chunks?page=1&page_size=100`, { headers })).json()
  expect(firstChunks.items.length).toBeGreaterThan(0)
  expect(bestChunks.items.length).toBeGreaterThan(0)
  const sourceIds = bestChunks.items.map((item: { id: number }) => item.id)

  await page.goto(
    `/courses/${courseId}/learn?kp_title=${encodeURIComponent('Target Knowledge')}`
      + `&kp_summary=${encodeURIComponent('Best material must be selected')}`
      + `&kp_source_chunk_ids=${encodeURIComponent(JSON.stringify(sourceIds))}`,
  )

  await expect(page.locator('.kp-focus-banner')).toContainText('Target Knowledge')
  await expect(page.locator('.kp-filter-note')).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('.material-select input')).toHaveValue('best.pdf', { timeout: 30_000 })
  await actualImageIsDecoded(page)
})

// T03: deletion must remove DB rows, FTS rows, and the material directory before re-upload.
test('T03 delete material cleans DB, FTS, and files before same-name re-upload', async ({ page, request }, testInfo) => {
  const { headers } = await registerUniqueUser(page, request, 'v753-t03')
  const courseId = await createCourse(request, headers, unique('T03'))
  const fixture = testInfo.outputPath('delete.pdf')
  generateEmbeddedPdf(fixture, 2, 'delete-cleanup')
  const oldId = await readyPdf(request, headers, courseId, fixture, 'delete.pdf')
  const before = runFixture('material-info', String(oldId))
  expect(before.exists).toBe(true)
  expect(before.counts.page_assets).toBeGreaterThan(0)
  expect(before.counts.chunks).toBeGreaterThan(0)

  const deletion = await request.delete(`${API_BASE}/materials/${oldId}`, { headers })
  expect(deletion.status()).toBe(204)
  const after = runFixture(
    'deleted-state',
    String(oldId),
    before.material_dir,
    JSON.stringify(before.chunk_ids),
  )
  expect(after).toEqual({
    material: 0,
    versions: 0,
    pages: 0,
    page_assets: 0,
    images: 0,
    chunks: 0,
    fts: 0,
    material_dir_exists: false,
  })

  const newId = await readyPdf(request, headers, courseId, fixture, 'delete.pdf')
  expect(newId).not.toBe(oldId)
  await page.goto(`/courses/${courseId}/learn`)
  await actualImageIsDecoded(page)
})

// T04: a legacy ready PDF with no page assets is repaired through the real UI button.
test('T04 legacy ready PDF without page assets is repaired from the frontend', async ({ page, request }, testInfo) => {
  const { headers } = await registerUniqueUser(page, request, 'v753-t04')
  const courseId = await createCourse(request, headers, unique('T04'))
  const fixture = testInfo.outputPath('repair.pdf')
  generateEmbeddedPdf(fixture, 2, 'repair-preview')
  const materialId = await readyPdf(request, headers, courseId, fixture, 'repair.pdf')
  const mutation = runFixture('remove-page-assets', String(materialId), '--break-first-image')
  expect(mutation.deleted_page_assets).toBe(2)
  expect(mutation.page_dir_exists).toBe(false)
  expect(mutation.broken_image_id).not.toBeNull()

  const before = await (await request.get(`${API_BASE}/materials/${materialId}/image-integrity`, { headers })).json()
  expect(before.expected_pages).toBe(2)
  expect(before.ready_pages).toBe(0)

  await page.goto(`/courses/${courseId}/learn`)
  const repair = page.getByRole('button', { name: '修复文档预览' }).first()
  await expect(repair).toBeVisible({ timeout: 30_000 })
  await repair.click()

  await expect.poll(async () => {
    const response = await request.get(`${API_BASE}/materials/${materialId}/image-integrity`, { headers })
    const body = await response.json()
    return `${body.ready_pages}/${body.expected_pages}:${body.status}`
  }, { timeout: 60_000, intervals: [500, 1_000, 2_000] }).toBe('2/2:page_fallback_ready')
  await expect(page.locator('.page-canvas')).toBeVisible({ timeout: 30_000 })
  await actualImageIsDecoded(page)
})

// T05: non-PDF materials must enter checked structured-text mode with real content.
test('T05 non-PDF material defaults to checked structured text mode', async ({ page, request }) => {
  const { headers } = await registerUniqueUser(page, request, 'v753-t05')
  const courseId = await createCourse(request, headers, unique('T05'))
  const materialId = await uploadBuffer(
    request,
    headers,
    courseId,
    Buffer.from('# Database Transactions\n\nAtomicity consistency isolation durability.\n\nA transaction groups related database operations.', 'utf-8'),
    'notes.md',
    'text/markdown',
  )
  expect(await waitForMaterialProcessed(request, headers, courseId, materialId)).toBe('ready')

  await page.goto(`/courses/${courseId}/learn`)
  const cleanRadio = page.getByRole('radio', { name: '结构化文本' })
  await expect(cleanRadio).toBeChecked({ timeout: 30_000 })
  const chunk = page.locator('.doc-chunk').first()
  await expect(chunk).toBeVisible()
  await expect(chunk).toContainText('transaction', { ignoreCase: true })
  await expect(page.locator('.page-canvas')).toHaveCount(0)
})

// T06: a scanned PDF remains readable when no semantic chunks exist.
test('T06 scanned PDF with zero chunks shows its decoded original page', async ({ page, request }, testInfo) => {
  const { headers } = await registerUniqueUser(page, request, 'v753-t06')
  const courseId = await createCourse(request, headers, unique('T06'))
  const fixture = testInfo.outputPath('scanned.pdf')
  generateScannedPdf(fixture)
  const materialId = await readyPdf(request, headers, courseId, fixture, 'scanned.pdf')
  const removed = runFixture('remove-chunks', String(materialId))
  expect(removed.fts_remaining).toBe(0)

  const chunks = await (await request.get(`${API_BASE}/materials/${materialId}/chunks?page=1&page_size=100`, { headers })).json()
  expect(chunks.total).toBe(0)
  const integrity = await (await request.get(`${API_BASE}/materials/${materialId}/image-integrity`, { headers })).json()
  expect(integrity.expected_pages).toBe(1)
  expect(integrity.ready_pages).toBe(1)

  await page.goto(`/courses/${courseId}/learn`)
  await expect(page.locator('.page-canvas')).toBeVisible({ timeout: 30_000 })
  await actualImageIsDecoded(page)
  await expect(page.locator('.image-error-banner')).toHaveCount(0)
})
