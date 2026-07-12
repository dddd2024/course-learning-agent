import { expect, type Page } from '@playwright/test'

export const TEST_USER = { username: 'test', password: 'test1234', email: 'test@example.com' }

/** Register against the actual backend when CI starts with an empty database. */
export async function loginWithFreshUser(page: Page) {
  const registration = await page.request.post('http://127.0.0.1:8000/api/v1/auth/register', { data: TEST_USER })
  // 201 means this run created the isolated user; 400/409 means a prior spec
  // already created it. Any other response is a real setup failure.
  expect([201, 400, 409]).toContain(registration.status())
  await page.goto('/login')
  await page.fill('input[placeholder="请输入用户名"]', TEST_USER.username)
  await page.fill('input[placeholder="请输入密码"]', TEST_USER.password)
  await page.click('button:has-text("登录")')
  await page.waitForURL('**/dashboard', { timeout: 15_000 })
}
