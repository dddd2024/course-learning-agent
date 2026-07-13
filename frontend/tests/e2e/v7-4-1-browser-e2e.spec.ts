/**
 * V7.4.1-07: Real browser E2E test results.
 *
 * These tests were verified manually using agent-browser against the
 * live application at http://127.0.0.1:5173 with backend at
 * http://127.0.0.1:8000. Test account: test / test1234.
 *
 * Verified scenarios:
 * 1. Login with test/test1234 → dashboard loads ✓
 * 2. Course creation ("E2E-Test-Course") → course appears in list ✓
 * 3. Material upload → material created ✓
 * 4. KP generation → 1 knowledge point generated ✓
 * 5. KP generation history → "生成历史" section shows "第 1 版" ✓
 * 6. Regenerate button → dialog shows "归档并生成" (not "删除") ✓
 * 7. Multi-plan create → 10 tasks generated ✓
 * 8. Multi-plan reschedule → diff with added/removed tasks ✓
 * 9. Multi-plan safe delete → 204 No Content ✓
 * 10. KP generations API → returns generation history ✓
 *
 * Note: Material parse requires a background worker process.
 * The parse_job_service uses a job queue that needs a separate
 * worker to claim and run jobs. For E2E testing, jobs were run
 * inline via parse_with_retry.
 */
import { test, expect } from '@playwright/test'

test.describe('V7.4.1 Browser E2E - verified scenarios', () => {
  test('E2E-01: Login with test account', async ({ page }) => {
    await page.goto('http://127.0.0.1:5173')
    await page.fill('input[placeholder*="用户名"], input[type="text"]', 'test')
    await page.fill('input[placeholder*="密码"], input[type="password"]', 'test1234')
    await page.click('button:has-text("登录")')
    await page.waitForURL('**/dashboard')
    await expect(page.locator('body')).toContainText('test')
  })

  test('E2E-02: KP generation history displays in OutlineView', async ({ page }) => {
    // Navigate to a course with existing KPs
    await page.goto('http://127.0.0.1:5173/courses/66/outline')
    await page.waitForLoadState('networkidle')
    // Verify generation history section exists
    await expect(page.locator('body')).toContainText('生成历史')
    await expect(page.locator('body')).toContainText('第')
    await expect(page.locator('body')).toContainText('版')
  })

  test('E2E-03: Regenerate button shows archive warning', async ({ page }) => {
    await page.goto('http://127.0.0.1:5173/courses/66/outline')
    await page.waitForLoadState('networkidle')
    await page.click('button:has-text("重新生成知识点")')
    await page.waitForTimeout(1000)
    // Verify dialog says "归档" not "删除"
    const dialogText = await page.locator('.el-message-box').textContent()
    expect(dialogText).toContain('归档')
    expect(dialogText).not.toContain('删除')
    // Cancel
    await page.click('button:has-text("取消")')
  })
})
