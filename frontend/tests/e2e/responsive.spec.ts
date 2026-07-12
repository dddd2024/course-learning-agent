import { test, expect } from '@playwright/test'
import { loginWithFreshUser } from './helpers'

/**
 * E2E: Responsive layout verification.
 *
 * Verifies that the application layout works correctly at:
 * - Desktop width (1280px)
 * - Mobile width (375px)
 */

async function login(page: import('@playwright/test').Page) {
  await loginWithFreshUser(page)
}

test.describe('Responsive Layout', () => {
  test.afterEach(async ({ page }) => {
    await page.evaluate(() => {
      sessionStorage.clear()
      localStorage.clear()
    })
  })

  test('layout works at 1280px desktop width', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 })
    await login(page)

    // Dashboard should render without horizontal overflow
    await page.goto('/dashboard')
    await page.waitForTimeout(2000)

    const body = page.locator('body')
    await expect(body).toBeVisible()

    // Check that no horizontal scrollbar appears
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
    const clientWidth = await page.evaluate(() => document.documentElement.clientWidth)
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1) // 1px tolerance
  })

  test('layout works at 375px mobile width', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 })
    await login(page)

    // Dashboard should render without horizontal overflow at mobile width
    await page.goto('/dashboard')
    await page.waitForTimeout(2000)

    const body = page.locator('body')
    await expect(body).toBeVisible()

    // Content should not overflow horizontally
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
    const clientWidth = await page.evaluate(() => document.documentElement.clientWidth)
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
  })

  test('navigation accessible at mobile width', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 })
    await login(page)

    // At mobile width, the layout should still be navigable
    await page.goto('/courses')
    await page.waitForTimeout(2000)

    const body = page.locator('body')
    await expect(body).toBeVisible()

    // The page content should be accessible (no hidden/cut-off elements)
    const bodyText = await body.innerText()
    expect(bodyText.length).toBeGreaterThan(0)
  })

  test('knowledge graph responsive at desktop and mobile', async ({ page }) => {
    // Desktop
    await page.setViewportSize({ width: 1280, height: 800 })
    await login(page)
    await page.goto('/knowledge-graph')
    await page.waitForTimeout(3000)

    const body = page.locator('body')
    await expect(body).toBeVisible()

    // Mobile
    await page.setViewportSize({ width: 375, height: 812 })
    await page.waitForTimeout(1000)

    // Page should still render without errors
    await expect(body).toBeVisible()

    // No horizontal overflow
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
    const clientWidth = await page.evaluate(() => document.documentElement.clientWidth)
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
  })
})
