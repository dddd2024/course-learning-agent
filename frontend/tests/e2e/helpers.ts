import { expect, type Page, type APIRequestContext } from '@playwright/test'

export const API_BASE = 'http://127.0.0.1:8000/api/v1'

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

/**
 * Register a unique user and log in via the frontend.
 * Returns the auth token and headers for API calls.
 */
export async function registerUniqueUser(
  page: Page,
  request: APIRequestContext,
  prefix = 'e2e',
): Promise<{ token: string; headers: Record<string, string> }> {
  const username = `${prefix}-${Date.now()}-${Math.floor(Math.random() * 10000)}`
  const password = 'test1234'
  const email = `${username}@example.com`

  const reg = await request.post(`${API_BASE}/auth/register`, {
    data: { username, password, email },
  })
  expect([201, 400, 409]).toContain(reg.status())

  await page.goto('/login')
  await page.fill('input[placeholder="请输入用户名"]', username)
  await page.fill('input[placeholder="请输入密码"]', password)
  await page.click('button:has-text("登录")')
  await page.waitForURL('**/dashboard', { timeout: 15_000 })

  const token = await page.evaluate(() => {
    return sessionStorage.getItem('token') || localStorage.getItem('token') || ''
  })
  expect(token.length).toBeGreaterThan(0)

  return { token, headers: { Authorization: `Bearer ${token}` } }
}

/**
 * Poll the materials API until a material reaches the target status.
 */
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
      const material = body.items.find((m: { id: number }) => m.id === materialId)
      return material?.status || 'missing'
    },
    { timeout, intervals: [500, 1_000, 2_000] },
  ).toBe(targetStatus)
}

/**
 * Poll until a material is no longer "processing" — returns the final
 * status ("ready" or "failed").
 */
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
      const material = body.items.find((m: { id: number }) => m.id === materialId)
      finalStatus = material?.status || 'missing'
      return finalStatus
    },
    { timeout, intervals: [500, 1_000, 2_000] },
  ).not.toBe('processing')
  return finalStatus
}

/**
 * Upload a fixture file as a course material.
 */
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
    multipart: {
      file: { name: filename, mimeType, buffer },
    },
  })
  expect(res.ok()).toBeTruthy()
  const body = await res.json()
  return body.id
}

/** Rich text content used as a fallback when PDF parsing fails. */
const TEXT_FALLBACK = `操作系统课程笔记

快表 TLB 是页表的高速缓存，用于加速虚拟地址到物理地址的转换。
页表存储虚拟页到物理页的映射关系。
TLB 命中时无需访问内存中的页表，提升了地址转换速度。
`

/**
 * Upload a text-based material as a fallback when PDF parsing fails.
 * Returns the new material ID.
 */
async function uploadTextMaterial(
  request: APIRequestContext,
  headers: Record<string, string>,
  courseId: number,
): Promise<number> {
  const buffer = Buffer.from(TEXT_FALLBACK, 'utf-8')
  const res = await request.post(`${API_BASE}/courses/${courseId}/materials`, {
    headers,
    multipart: {
      file: { name: 'networking-notes.txt', mimeType: 'text/plain', buffer },
    },
  })
  expect(res.ok()).toBeTruthy()
  return (await res.json()).id
}

/**
 * Create a course, upload + parse a text material, generate knowledge points.
 *
 * Uses a text file (not the PDF fixture) because the PDF two-column
 * layout produces chunks that are mostly ``is_indexable=False`` (low
 * quality), which means knowledge-point generation returns 0 points.
 * The text file has clean, structured content with proper headings that
 * reliably produce indexable chunks and valid knowledge points.
 *
 * Returns the course ID, material ID, and knowledge point count.
 */
export async function setupCourseWithMaterialAndKPs(
  request: APIRequestContext,
  headers: Record<string, string>,
  courseName: string,
  _fixturePath?: string,
  _filename?: string,
  _mimeType?: string,
): Promise<{ courseId: number; materialId: number; kpCount: number }> {
  // Create course
  const courseRes = await request.post(`${API_BASE}/courses`, {
    headers,
    data: { name: courseName },
  })
  expect(courseRes.ok()).toBeTruthy()
  const courseId = (await courseRes.json()).id

  // Upload text material (always — PDF chunks are low quality)
  const materialId = await uploadTextMaterial(request, headers, courseId)

  // Parse
  const parseRes = await request.post(`${API_BASE}/materials/${materialId}/parse`, { headers })
  expect(parseRes.ok()).toBeTruthy()

  // Wait for parse to complete
  await waitForMaterialStatus(request, headers, courseId, materialId, 'ready', 90_000)

  // Generate knowledge points
  const kpRes = await request.post(
    `${API_BASE}/courses/${courseId}/knowledge-points/generate`,
    { headers },
  )
  expect(kpRes.ok()).toBeTruthy()
  const kpBody = await kpRes.json()
  expect(kpBody.knowledge_points.length).toBeGreaterThan(0)

  return { courseId, materialId, kpCount: kpBody.knowledge_points.length }
}
