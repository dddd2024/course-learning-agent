/** V7.5.0 document-reader acceptance using a runtime-generated PDF fixture. */
import { expect, test, type Page, type TestInfo } from '@playwright/test'
import { existsSync } from 'fs'
import { resolve } from 'path'
import { execFileSync } from 'child_process'

function tag() {
  return `v750-${Date.now()}-${Math.floor(Math.random() * 100_000)}`
}

function generateVectorPdf(path: string) {
  const projectRoot = resolve(process.cwd(), '..')
  const python = resolve(projectRoot, 'backend', '.venv', 'Scripts', 'python.exe')
  const executable = existsSync(python) ? python : 'python'
  const program = [
    'import fitz, sys',
    'doc = fitz.open()',
    'page = doc.new_page()',
    "page.insert_text((72, 72), 'Runtime vector PDF fixture: original-page reader', fontsize=16)",
    'page.draw_rect(fitz.Rect(72, 120, 360, 260), color=(0, 0.35, 0.75), fill=(0.9, 0.95, 1))',
    'page.draw_line((90, 240), (330, 140), color=(0.85, 0.1, 0.1), width=3)',
    "page.insert_text((92, 180), 'vector diagram', fontsize=14)",
    'doc.save(sys.argv[1])',
  ].join('; ')
  execFileSync(executable, ['-c', program, path], { stdio: 'inherit' })
}

async function registerThroughUi(page: Page) {
  const username = tag()
  await page.goto('/login')
  await page.getByRole('tab', { name: '注册' }).click()
  await page.locator('input[placeholder="请输入用户名"]').last().fill(username)
  await page.locator('input[placeholder="至少 6 位"]').fill('test1234')
  await page.locator('input[placeholder="再次输入密码"]').fill('test1234')
  await page.locator('input[placeholder="选填"]').fill(`${username}@example.test`)
  await page.getByRole('button', { name: '注册并登录' }).click()
  await expect(page).toHaveURL(/\/dashboard/)
}

async function createCourseThroughUi(page: Page): Promise<number> {
  const name = `V7.5 document ${tag()}`
  await page.goto('/courses')
  await page.getByRole('button', { name: '新建课程' }).first().click()
  const dialog = page.getByRole('dialog', { name: '新建课程' })
  await dialog.locator('input').first().fill(name)
  const created = page.waitForResponse((response) => response.url().includes('/api/v1/courses')
    && response.request().method() === 'POST' && response.ok())
  await dialog.getByRole('button', { name: '确定' }).click()
  return Number((await (await created).json()).id)
}

test('V7.5.0-E2E: runtime-generated PDF is read through the original-page UI', async ({ page }, testInfo) => {
  await registerThroughUi(page)
  const courseId = await createCourseThroughUi(page)
  const fixture = testInfo.outputPath('runtime-vector-fixture.pdf')
  generateVectorPdf(fixture)

  await page.goto(`/courses/${courseId}/materials`)
  await page.locator('input[type="file"]').setInputFiles(fixture)
  await expect(page.locator('tbody').getByText('已就绪', { exact: true })).toBeVisible({ timeout: 90_000 })

  const pageAssetResponse = page.waitForResponse((response) => response.url().includes('/page-assets/')
    && response.request().method() === 'GET', { timeout: 15_000 })
  await page.goto(`/courses/${courseId}/learn`)
  await expect(page.getByRole('radiogroup', { name: '资料展示模式' })).toContainText('原页')
  await expect(page.locator('.page-canvas')).toBeVisible({ timeout: 30_000 })
  const assetResponse = await pageAssetResponse
  expect(assetResponse.status(), await assetResponse.text()).toBe(200)
  await expect(page.getByAltText('资料第 1 页原页图像')).toBeVisible({ timeout: 30_000 })
  const textBlock = page.locator('.text-layer [data-block-id]').first()
  await expect(textBlock).toBeAttached()
  await textBlock.evaluate((element) => {
    const range = document.createRange()
    range.selectNodeContents(element)
    const selection = window.getSelection()
    selection?.removeAllRanges()
    selection?.addRange(range)
    element.parentElement?.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
  })
  await expect(page.locator('.selected-text-box')).toContainText('第 1 页')
  const chatRequest = page.waitForRequest((request) => request.url().endsWith('/api/v1/chat') && request.method() === 'POST')
  await page.getByRole('button', { name: '问AI：这段什么意思？' }).click()
  const payload = (await chatRequest).postDataJSON()
  expect(payload.selection_context.material_id).toBeGreaterThan(0)
  expect(payload.selection_context.page_no).toBe(1)
  expect(payload.selection_context.selected_text).toContain('Runtime vector PDF fixture')
  expect(payload.selection_context.source_block_ids.length).toBeGreaterThan(0)
  await page.screenshot({ path: testInfo.outputPath('document-reader.png'), fullPage: true })
})
