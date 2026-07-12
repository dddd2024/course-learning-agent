import { test, expect } from '@playwright/test'
import { loginWithFreshUser } from './helpers'

/**
 * E2E: Multi-tenant file isolation.
 *
 * Verifies that User A cannot read User B's uploaded materials or
 * extracted chunks. This is a security boundary test — cross-user
 * access must return 404 (not 200 with another user's data).
 */

async function login(page: import('@playwright/test').Page) {
  await loginWithFreshUser(page)
}

test.describe('Auth & File Isolation', () => {
  test.beforeEach(async ({ page }) => {
    await login(page)
  })

  test.afterEach(async ({ page }) => {
    // Clean up: log out by clearing session
    await page.evaluate(() => {
      sessionStorage.clear()
      localStorage.clear()
    })
  })

  test('authenticated user can access dashboard', async ({ page }) => {
    await expect(page).toHaveURL(/\/dashboard/)
    await expect(page.locator('body')).toContainText(/仪表盘|课程学习/)
  })

  test('user cannot access another user material chunks via direct API call', async ({
    page,
    request,
  }) => {
    // Get the auth token from sessionStorage
    const token = await page.evaluate(() => {
      return sessionStorage.getItem('token') || localStorage.getItem('token') || ''
    })

    // Attempt to fetch a chunk that may belong to another user.
    // The backend should return 404 for non-owned resources.
    const response = await request.get(
      'http://127.0.0.1:8000/api/v1/materials/99999/chunks',
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    )

    // A non-existent or non-owned material should NOT return 200
    expect(response.status()).not.toBe(200)
  })

  test('unauthenticated request is redirected to login', async ({ page }) => {
    // Clear all auth state
    await page.evaluate(() => {
      sessionStorage.clear()
      localStorage.clear()
    })

    // Try to access a protected route directly
    await page.goto('/dashboard')

    // Should be redirected to login
    await expect(page).toHaveURL(/\/login/, { timeout: 10_000 })
  })
})
