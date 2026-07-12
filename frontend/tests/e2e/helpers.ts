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
const TEXT_FALLBACK = `计算机网络基础

网络协议是计算机网络中进行数据交换而建立的规则、标准或约定的集合。网络协议由三个要素组成：语义、语法和时序。

TCP/IP协议族是互联网的基础协议。TCP提供可靠的、面向连接的数据传输服务，而IP则负责将数据包从源主机发送到目标主机。

OSI七层模型将网络通信划分为七个层次：物理层、数据链路层、网络层、传输层、会话层、表示层和应用层。每一层都有特定的功能和协议。

路由算法是网络层的核心功能之一。常见的路由算法包括距离向量算法和链路状态算法。OSPF协议使用链路状态算法，而RIP协议使用距离向量算法。

网络安全是现代计算机网络的重要组成部分。加密技术、防火墙、入侵检测系统等都是保障网络安全的关键技术。SSL/TLS协议为网络通信提供了加密和身份验证功能。

DNS域名系统是互联网的基础服务之一。它将人类可读的域名转换为IP地址，使得用户可以通过域名访问网络服务。DNS采用层次化的分布式数据库结构。

HTTP协议是Web应用的基础协议。HTTP/1.1引入了持久连接和管道化技术，HTTP/2引入了多路复用和头部压缩，HTTP/3则基于QUIC协议提供了更快的传输速度。

无线网络技术包括Wi-Fi、蓝牙和5G等。Wi-Fi基于IEEE 802.11标准，提供了无线局域网接入能力。5G网络提供了更高的带宽和更低的延迟。
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
