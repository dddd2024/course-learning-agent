import { expect, type Page, type APIRequestContext } from '@playwright/test'
import { backendPort } from './e2e-runtime'

export const API_BASE = `http://127.0.0.1:${backendPort}/api/v1`
export const TEST_USER = { username: 'test', password: 'test1234', email: 'test@example.com' }

export async function loginWithFreshUser(page: Page) {
  const registration = await page.request.post(`${API_BASE}/auth/register`, { data: TEST_USER })
  expect([201, 400, 409]).toContain(registration.status())
  await page.goto('/login')
  await page.fill('input[placeholder="请输入用户名"]', TEST_USER.username)
  await page.fill('input[placeholder="请输入密码"]', TEST_USER.password)
  await page.click('button:has-text("登录")')
  await page.waitForURL('**/dashboard', { timeout: 15_000 })
}

export async function registerUniqueUser(
  page: Page,
  request: APIRequestContext,
  prefix = 'e2e',
): Promise<{ token: string; headers: Record<string, string>; username: string }> {
  const username = `${prefix}-${Date.now()}-${Math.floor(Math.random() * 10000)}`
  const password = 'test1234'
  const email = `${username}@example.com`

  const reg = await request.post(`${API_BASE}/auth/register`, {
    data: { username, password, email },
  })
  expect(reg.status()).toBe(201)

  await page.goto('/login')
  await page.fill('input[placeholder="请输入用户名"]', username)
  await page.fill('input[placeholder="请输入密码"]', password)
  await page.click('button:has-text("登录")')
  await page.waitForURL('**/dashboard', { timeout: 15_000 })

  const token = await page.evaluate(() => {
    return sessionStorage.getItem('token') || localStorage.getItem('token') || ''
  })
  expect(token.length).toBeGreaterThan(0)
  return { token, headers: { Authorization: `Bearer ${token}` }, username }
}

export async function createCourse(
  request: APIRequestContext,
  headers: Record<string, string>,
  name: string,
): Promise<number> {
  const response = await request.post(`${API_BASE}/courses`, { headers, data: { name } })
  expect(response.ok()).toBeTruthy()
  return (await response.json()).id
}

export async function waitForMaterialStatus(
  request: APIRequestContext,
  headers: Record<string, string>,
  courseId: number,
  materialId: number,
  targetStatus: string,
  timeout = 60_000,
): Promise<void> {
  await expect.poll(
    async () => {
      const res = await request.get(`${API_BASE}/courses/${courseId}/materials`, { headers })
      if (!res.ok()) return `HTTP ${res.status()}`
      const body = await res.json()
      const material = body.items.find((item: { id: number }) => item.id === materialId)
      return material?.status || 'missing'
    },
    { timeout, intervals: [500, 1_000, 2_000] },
  ).toBe(targetStatus)
}

export async function waitForMaterialProcessed(
  request: APIRequestContext,
  headers: Record<string, string>,
  courseId: number,
  materialId: number,
  timeout = 90_000,
): Promise<string> {
  let finalStatus = 'processing'
  await expect.poll(
    async () => {
      const res = await request.get(`${API_BASE}/courses/${courseId}/materials`, { headers })
      if (!res.ok()) return `HTTP ${res.status()}`
      const body = await res.json()
      const material = body.items.find((item: { id: number }) => item.id === materialId)
      finalStatus = material?.status || 'missing'
      return finalStatus
    },
    { timeout, intervals: [500, 1_000, 2_000] },
  ).not.toBe('processing')
  return finalStatus
}

export async function uploadMaterial(
  request: APIRequestContext,
  headers: Record<string, string>,
  courseId: number,
  fixturePath: string,
  filename: string,
  mimeType: string,
): Promise<number> {
  const fs = await import('fs')
  const buffer = fs.readFileSync(fixturePath)
  const res = await request.post(`${API_BASE}/courses/${courseId}/materials`, {
    headers,
    multipart: { file: { name: filename, mimeType, buffer } },
  })
  expect(res.ok()).toBeTruthy()
  return (await res.json()).id
}

export async function uploadBuffer(
  request: APIRequestContext,
  headers: Record<string, string>,
  courseId: number,
  buffer: Buffer,
  filename: string,
  mimeType: string,
): Promise<number> {
  const res = await request.post(`${API_BASE}/courses/${courseId}/materials`, {
    headers,
    multipart: { file: { name: filename, mimeType, buffer } },
  })
  expect(res.ok()).toBeTruthy()
  return (await res.json()).id
}

export async function parseMaterial(
  request: APIRequestContext,
  headers: Record<string, string>,
  courseId: number,
  materialId: number,
): Promise<void> {
  const response = await request.post(`${API_BASE}/materials/${materialId}/parse`, { headers })
  expect(response.ok()).toBeTruthy()
  await waitForMaterialStatus(request, headers, courseId, materialId, 'ready', 90_000)
}
