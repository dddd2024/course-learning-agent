/**
 * V7.4.3 browser acceptance: all business actions below are performed through
 * visible controls.  There is intentionally no Playwright request fixture in
 * this file: server health is owned by playwright.config.ts, while course,
 * material, plan, quiz, reschedule and archive actions stay page-driven.
 */
import { test, expect, type Page } from '@playwright/test'

test.describe.configure({ mode: 'serial', timeout: 300_000 })

const suffix = `${Date.now()}-${Math.floor(Math.random() * 10_000)}`
const materialText = `核心概念：TCP/IP 协议簇用于端到端通信。HTTP/2 通过多路复用提升传输效率。
知识框架：CSMA/CD 用于共享以太网的冲突检测。客户端和服务器通过请求与响应协作。
`

async function registerThroughUi(page: Page, tag: string) {
  const username = `v743-${tag}-${suffix}`
  await page.goto('/login')
  await page.getByRole('tab', { name: '注册' }).click()
  await page.locator('input[placeholder="请输入用户名"]').last().fill(username)
  await page.locator('input[placeholder="至少 6 位"]').fill('test1234')
  await page.locator('input[placeholder="再次输入密码"]').fill('test1234')
  await page.locator('input[placeholder="选填"]').fill(`${username}@example.com`)
  await page.getByRole('button', { name: '注册并登录' }).click()
  await page.waitForURL('**/dashboard')
}

async function createCourse(page: Page, name: string): Promise<number> {
  await page.goto('/courses')
  await page.getByRole('button', { name: '新建课程' }).first().click()
  const dialog = page.locator('.el-dialog').filter({ hasText: '新建课程' })
  await dialog.locator('input').first().fill(name)
  const created = page.waitForResponse((response) =>
    response.url().includes('/api/v1/courses')
    && response.request().method() === 'POST'
    && response.status() >= 200 && response.status() < 300,
  )
  await dialog.getByRole('button', { name: '确定' }).click()
  const courseId = Number((await (await created).json()).id)
  await expect(page.getByRole('button', { name: `打开课程 ${name}` })).toBeVisible()
  return courseId
}

async function prepareCourse(page: Page, tag: string, materialFilename = '核心概念.txt'): Promise<number> {
  const name = `V743-${tag}-${suffix}`
  const courseId = await createCourse(page, name)
  await page.goto(`/courses/${courseId}/materials`)
  await page.locator('input[type="file"]').setInputFiles({
    name: materialFilename, mimeType: 'text/plain', buffer: Buffer.from(materialText),
  })
  await expect(page.locator('tbody').getByText('已就绪', { exact: true })).toBeVisible({ timeout: 90_000 })
  await page.goto(`/courses/${courseId}/outline`)
  await page.getByRole('button', { name: '生成知识点' }).first().click()
  await page.getByRole('button', { name: '生成', exact: true }).click()
  await expect(page.getByText('知识点列表')).toBeVisible({ timeout: 60_000 })
  await expect(page.locator('.kp-card')).not.toHaveCount(0)
  return courseId
}

async function createPlan(page: Page, courseName: string) {
  await page.goto('/plans')
  // A new account lands directly on the form.  Waiting for it avoids racing
  // the saved-plan list's initial render, which may briefly expose the action.
  const goal = page.locator('textarea[placeholder*="7 天复习"]')
  await expect(goal).toBeVisible()
  await goal.fill(`完成 ${courseName}`)
  await page.getByText('请选择课程', { exact: true }).click()
  await page.getByText(courseName, { exact: true }).last().click()
  await page.getByRole('combobox', { name: '截止日期' }).fill('2026-12-31')
  await page.getByRole('button', { name: '生成并保存计划' }).click()
  await expect(page.getByText('阶段任务', { exact: true })).toBeVisible({ timeout: 60_000 })
}

async function answerTaskQuiz(page: Page, pass: boolean) {
  const quiz = page
  const nav = quiz.locator('.question-nav .qnav-btn')
  await expect(nav.first()).toBeVisible({ timeout: 60_000 })
  const count = await nav.count()
  for (let index = 0; index < count; index += 1) {
    await nav.nth(index).click()
    await page.waitForTimeout(100)
    if (await page.getByText('简答题', { exact: true }).isVisible()) {
      await page.locator('textarea[placeholder="请输入答案"]').fill(pass ? '知识框架' : '错误答案')
      continue
    }
    if (await page.getByText('判断题', { exact: true }).isVisible()) {
      await page.keyboard.press(pass ? 't' : 'f')
      continue
    }
    const radios = page.getByRole('radio')
    if (await radios.count()) {
      if (!pass) {
        await radios.last().check()
      } else if (await page.getByRole('radio', { name: '正确' }).count()) {
        await page.getByRole('radio', { name: '正确' }).check()
      } else {
        // Mock-backed choice questions place the evidence-supported answer
        // first.  Do not couple this browser flow to one fixture sentence.
        await radios.first().check()
      }
    } else {
      await quiz.locator('textarea').fill(pass ? '知识框架' : '错误答案')
    }
  }
  await page.getByRole('button', { name: '提交测验' }).click()
  await expect(page.getByText('得分：')).toBeVisible()
}

async function waitForQuizGeneration(page: Page, jobId: number): Promise<number> {
  const terminal = await page.waitForResponse(async (response) => {
    if (
      !response.url().endsWith(`/api/v1/quizzes/generation-jobs/${jobId}`)
      || response.request().method() !== 'GET'
      || !response.ok()
    ) return false
    const body = await response.json().catch(() => null)
    return body?.status === 'succeeded' || body?.status === 'failed'
  }, { timeout: 60_000 })
  const body = await terminal.json()
  expect(body.status, body.error_message || 'quiz generation did not succeed').toBe('succeeded')
  expect(Number(body.quiz_id)).toBeGreaterThan(0)
  return Number(body.quiz_id)
}

test('V7.4.3-E2E-01: registration and dashboard are browser-visible', async ({ page }) => {
  await registerThroughUi(page, 'auth')
  await expect(page.getByRole('heading', { name: '仪表盘' })).toBeVisible()
})

test('V7.4.3-E2E-02: create, upload, parse, search, and inspect source through UI', async ({ page }) => {
  await registerThroughUi(page, 'material')
  const courseId = await prepareCourse(page, 'material')
  await page.goto(`/courses/${courseId}/materials`)
  await page.getByRole('button', { name: '查看片段' }).first().click()
  await expect(page.getByRole('dialog')).toContainText('片段列表')
  await page.getByRole('dialog').locator('.el-dialog__headerbtn').click()
  await page.locator('input[placeholder="输入关键词检索课程资料片段"]').fill('TCP/IP')
  await page.getByRole('button', { name: '检索' }).click()
  await expect(page.getByText('检索结果')).toBeVisible()
})

test('V7.4.3-E2E-03: plan starts learn task and confirms it on reader page', async ({ page }) => {
  await registerThroughUi(page, 'learn')
  const name = `V743-learn-${suffix}`
  await prepareCourse(page, 'learn')
  await createPlan(page, name)
  await page.getByRole('button', { name: '开始学习' }).click()
  await page.waitForURL(/\/learn/)
  await expect(page.getByRole('button', { name: '完成本次学习' })).toBeVisible()
  await page.getByRole('button', { name: '完成本次学习' }).click()
  await expect(page).toHaveURL(/\/plans/)
})

test('V7.4.3-E2E-04: plan starts review task and confirms it on outline page', async ({ page }) => {
  await registerThroughUi(page, 'review')
  const name = `V743-review-${suffix}`
  await prepareCourse(page, 'review')
  await createPlan(page, name)
  await page.getByRole('button', { name: '复习知识点' }).first().click()
  await page.waitForURL(/\/outline/)
  await page.getByRole('button', { name: '完成本次复习' }).click()
  await expect(page).toHaveURL(/\/plans/)
})

test('V7.4.3-E2E-05: custom quiz contract is created and passed through UI', async ({ page }) => {
  await registerThroughUi(page, 'quiz-pass')
  const courseId = await prepareCourse(page, 'quiz-pass')
  await page.goto(`/quizzes?course_id=${courseId}`)
  await page.getByRole('button', { name: '生成测验' }).click()
  const dialog = page.getByRole('dialog', { name: '生成测验' })
  const numbers = dialog.getByRole('spinbutton')
  await numbers.nth(0).fill('1')
  await numbers.nth(1).fill('1')
  await numbers.nth(2).fill('0')
  await numbers.nth(3).fill('0')
  await dialog.getByText('单选题').click() // leave only true/false in the requested contract
  await dialog.getByText('多选题').click()
  await dialog.getByText('简答题').click()
  await dialog.getByRole('button', { name: '生成', exact: true }).click()
  await expect(page.locator('input[type="radio"]').first()).toBeVisible({ timeout: 60_000 })
  await page.locator('input[type="radio"][value="true"]').check()
  await page.getByRole('button', { name: '提交测验' }).click()
  await expect(page.getByText('得分：')).toBeVisible()
})

test('V7.4.3-E2E-06: a failed task quiz creates a fresh retry which can pass', async ({ page }) => {
  await registerThroughUi(page, 'quiz-fail')
  const name = `V743-quiz-fail-${suffix}`
  await prepareCourse(page, 'quiz-fail')
  await createPlan(page, name)
  const queued = page.waitForResponse((response) =>
    /\/plans\/tasks\/\d+\/quiz-generation-job$/.test(response.url())
    && response.request().method() === 'POST'
    && response.ok(),
  )
  await page.locator('button:not(:disabled)', { hasText: '生成测验' }).first().click()
  const job = await (await queued).json()
  expect(Number(job.id)).toBeGreaterThan(0)
  await waitForQuizGeneration(page, Number(job.id))
  await page.waitForURL(/\/quizzes/)
  await answerTaskQuiz(page, false)
  await page.goto('/plans')
  await expect(page.getByRole('button', { name: '重新练习' })).toBeVisible()
  await page.getByRole('button', { name: '重新练习' }).click()
  await page.waitForURL(/\/quizzes/)
  await answerTaskQuiz(page, true)
  await page.goto('/plans')
  await expect(page.getByText('已完成', { exact: true }).first()).toBeVisible()
})

test('V7.4.3-E2E-07: multi-plan reschedule diff and persisted history are visible', async ({ page }) => {
  await registerThroughUi(page, 'multi')
  const name = `V743-multi-${suffix}`
  await prepareCourse(page, 'multi', '学习课程资料.txt')
  await page.goto('/plans/multi')
  await page.getByRole('row', { name: new RegExp(name) }).locator('.el-checkbox').click()
  await page.getByRole('button', { name: '生成综合计划' }).click()
  await expect(page.getByRole('button', { name: '重新调度' })).toBeVisible({ timeout: 60_000 })
  await page.getByRole('button', { name: '重新调度' }).click()
  await page.getByRole('dialog', { name: '重新调度' }).getByRole('button', { name: '重新调度' }).click()
  await expect(page.getByRole('dialog', { name: '重排差异对比' })).toBeVisible()
  await page.getByRole('button', { name: '关闭' }).last().click()
  await page.getByRole('button', { name: '历史记录' }).click()
  await expect(page.getByText('重排批次')).toBeVisible()
  await page.getByRole('button', { name: '查看差异' }).click()
  await expect(page.getByRole('dialog', { name: '重排差异对比' })).toBeVisible()
  await page.getByRole('button', { name: '关闭' }).last().click()

  // Multi-plan tasks are surfaced in the normal plan UI.  Completing one
  // through that UI creates the execution history which must block deletion.
  await page.goto('/plans')
  await expect(page.getByText('阶段任务', { exact: true })).toBeVisible()
  const evidenceLoaded = page.waitForResponse((response) =>
    response.url().includes('/plans/tasks/') && response.url().endsWith('/events')
    && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '开始学习' }).click()
  await page.waitForURL(/\/learn/)
  await expect((await evidenceLoaded).status()).toBe(200)
  await page.getByRole('button', { name: '完成本次学习' }).click()
  await page.waitForURL(/\/plans/)

  await page.goto('/plans/multi')
  await page.getByText('选择要查看的计划', { exact: true }).click()
  await page.getByText('多课程学习计划', { exact: true }).last().click()
  await expect(page.getByRole('button', { name: '删除计划' })).toBeVisible()
  await page.getByRole('button', { name: '删除计划' }).click()
  await page.getByRole('dialog', { name: '删除计划' }).getByRole('button', { name: '删除' }).click()
  await page.getByRole('dialog', { name: '归档计划' }).getByRole('button', { name: '归档' }).click()
  await expect(page.getByText('多课程计划已归档')).toBeVisible()
})

test('V7.4.3-E2E-08: historical KP generation is read-only and returns current view', async ({ page }) => {
  await registerThroughUi(page, 'history')
  const courseId = await prepareCourse(page, 'history')
  await page.goto(`/courses/${courseId}/outline`)
  await page.getByRole('button', { name: '重新生成知识点' }).click()
  await page.getByRole('button', { name: '归档并生成' }).click()
  await expect(page.getByText('生成历史')).toBeVisible({ timeout: 60_000 })
  await page.getByText('第 1 版').click()
  await expect(page.getByText('只读历史模式')).toBeVisible()
  await expect(page.getByRole('button', { name: '生成知识点' })).toHaveCount(0)
  await page.getByRole('button', { name: '返回当前版本' }).click()
  await expect(page.getByRole('button', { name: '重新生成知识点' })).toBeVisible()
})
