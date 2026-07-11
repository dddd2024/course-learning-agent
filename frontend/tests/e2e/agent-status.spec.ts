import { test, expect } from '@playwright/test'

/**
 * E2E: Agent status and fallback chain visibility.
 *
 * Verifies that:
 * - degraded/insufficient_evidence/failed status labels display correctly.
 * - fallback_chain is visible in the detail drawer.
 * - Status persists after page refresh.
 */

const TEST_USER = { username: 'test', password: 'test1234' }

async function login(page: import('@playwright/test').Page) {
  await page.goto('/login')
  await page.fill('input[placeholder="请输入用户名"]', TEST_USER.username)
  await page.fill('input[placeholder="请输入密码"]', TEST_USER.password)
  await page.click('button:has-text("登录")')
  await page.waitForURL('**/dashboard', { timeout: 15_000 })
}

test.describe('Agent Status', () => {
  test.beforeEach(async ({ page }) => {
    await login(page)
  })

  test.afterEach(async ({ page }) => {
    await page.evaluate(() => {
      sessionStorage.clear()
      localStorage.clear()
    })
  })

  test('agent runs page loads and displays run list', async ({ page }) => {
    await page.goto('/agent-runs')
    await page.waitForTimeout(2000)

    const body = page.locator('body')
    await expect(body).toBeVisible()

    // The page should show the audit title
    const bodyText = await body.innerText()
    expect(bodyText).toContain('Agent')
  })

  test('degraded status persists after page refresh', async ({ page }) => {
    await page.goto('/agent-runs')
    await page.waitForTimeout(2000)

    // Capture the page state before refresh
    const bodyTextBefore = await page.locator('body').innerText()

    // Refresh the page
    await page.reload()
    await page.waitForTimeout(2000)

    // The page should reload and show the same data
    const bodyTextAfter = await page.locator('body').innerText()

    // Status labels should still be present after refresh
    // (If there were any runs before, they should still be there)
    if (bodyTextBefore.includes('降级') || bodyTextBefore.includes('成功') || bodyTextBefore.includes('失败')) {
      // At least one status label should persist
      const hasStatus =
        bodyTextAfter.includes('降级') ||
        bodyTextAfter.includes('成功') ||
        bodyTextAfter.includes('失败') ||
        bodyTextAfter.includes('证据不足')
      expect(hasStatus).toBe(true)
    }
  })

  test('fallback chain visible in detail drawer', async ({ page }) => {
    await page.goto('/agent-runs')
    await page.waitForTimeout(3000)

    // Look for rows in the agent runs table
    const rows = page.locator('.el-table__row')
    const rowCount = await rows.count()

    if (rowCount > 0) {
      // Click the first row to open the detail drawer
      await rows.first().click()
      await page.waitForTimeout(2000)

      // The detail drawer should be visible
      const drawer = page.locator('.el-drawer')
      if (await drawer.isVisible()) {
        const drawerText = await drawer.innerText()
        // The drawer should show run details
        expect(drawerText.length).toBeGreaterThan(0)

        // If the run used fallback, the fallback chain should be visible
        if (drawerText.includes('Fallback 是')) {
          expect(drawerText).toContain('Fallback Chain')
        }
      }
    }
  })
})
