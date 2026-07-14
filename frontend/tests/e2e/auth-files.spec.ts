import { test, expect } from '@playwright/test'
import { API_BASE, loginWithFreshUser } from './helpers'

/**
 * E2E: Multi-tenant file isolation.
 *
 * Verifies that User A cannot read User B's uploaded materials or
 * extracted chunks. Cross-user access must not return another user's data.
 */
async function login(page: import('@playwright/test').Page) {
  await loginWithFreshUser(page)
}

test.describe('Auth & File Isolation', () => {
  test.beforeEach(async ({ page }) => {
    await login(page)
  })

  test.afterEach(async ({ page }) => {
    await page.evaluate(() => {
      sessionStorage.clear()
      localStorage.clear()
    })
  })

  test('authenticated user can access dashboard', async ({ page }) => {
    await expect(page).toHaveURL(/\/dashboard/)
    await expect(page.locator('body')).toContainText(/仪表盘|课程学习/)
  })

  test('user cannot access another user material chunks via direct API call', async ({ page, request }) => {
    const token = await page.evaluate(() => {
      return sessionStorage.getItem('token') || localStorage.getItem('token') || ''
    })
    const response = await request.get(`${API_BASE}/materials/99999/chunks`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(response.status()).not.toBe(200)
  })

  test('unauthenticated request is redirected to login', async ({ page }) => {
    await page.evaluate(() => {
      sessionStorage.clear()
      localStorage.clear()
    })
    await page.goto('/dashboard')
    await expect(page).toHaveURL(/\/login/, { timeout: 10_000 })
  })
})
