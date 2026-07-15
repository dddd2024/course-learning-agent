/**
 * V7.4.4 release-browser acceptance.
 *
 * Every scenario creates its own account and course through visible controls.
 * There is deliberately no APIRequestContext, fixed sleep, serial suite, or
 * conditional success path in this file: network responses are observed only
 * to synchronize a user-initiated browser action.
 */
import { test, expect, type Page, type TestInfo } from '@playwright/test'

const materialText = `核心概念：TCP/IP 协议簇用于端到端通信。
HTTP 通过请求和响应协作，客户端和服务器使用网络协议交换信息。
CSMA/CD 用于共享以太网的冲突检测。`

function runTag(name: string) {
  return `v744-${name}-${Date.now()}-${Math.floor(Math.random() * 100_000)}`
}

async function saveFinalScreenshot(page: Page, testInfo: TestInfo) {
  await page.screenshot({ path: testInfo.outputPath('final-state.png'), fullPage: true })
}

async function registerThroughUi(page: Page, tag: string) {
  const username = runTag(tag)
  await page.goto('/login')
  await page.getByRole('tab', { name: '注册' }).click()
  await page.locator('input[placeholder="请输入用户名"]').last().fill(username)
  await page.locator('input[placeholder="至少 6 位"]').fill('test1234')
  await page.locator('input[placeholder="再次输入密码"]').fill('test1234')
  await page.locator('input[placeholder="选填"]').fill(`${username}@example.com`)
  await page.getByRole('button', { name: '注册并登录' }).click()
  await expect(page).toHaveURL(/\/dashboard/)
  return username
}

async function createCourse(page: Page, name: string): Promise<number> {
  await page.goto('/courses')
  await page.getByRole('button', { name: '新建课程' }).first().click()
  const dialog = page.getByRole('dialog', { name: '新建课程' })
  await dialog.locator('input').first().fill(name)
  const created = page.waitForResponse((response) =>
    response.url().includes('/api/v1/courses')
    && response.request().method() === 'POST'
    && response.ok(),
  )
  await dialog.getByRole('button', { name: '确定' }).click()
  const id = Number((await (await created).json()).id)
  expect(id).toBeGreaterThan(0)
  await expect(page.getByRole('button', { name: `打开课程 ${name}` })).toBeVisible()
  return id
}

async function prepareCourse(page: Page, tag: string): Promise<{ id: number; name: string }> {
  const name = `V744-${tag}-${runTag('course')}`
  const id = await createCourse(page, name)
  await page.goto(`/courses/${id}/materials`)
  await page.locator('input[type="file"]').setInputFiles({
    name: 'network-notes.txt', mimeType: 'text/plain', buffer: Buffer.from(materialText),
  })
  await expect(page.locator('tbody').getByText('已就绪', { exact: true })).toBeVisible({ timeout: 90_000 })
  await page.goto(`/courses/${id}/outline`)
  await page.getByRole('button', { name: '生成知识点' }).first().click()
  const generated = page.waitForResponse((response) =>
    response.url().includes('/knowledge-points/generate')
    && response.request().method() === 'POST'
    && response.ok(),
  )
  await page.getByRole('button', { name: '生成', exact: true }).click()
  await generated
  await expect(page.locator('.kp-card').first()).toBeVisible({ timeout: 60_000 })
  return { id, name }
}

async function createPlan(page: Page, courseName: string) {
  await page.goto('/plans')
  const goal = page.locator('textarea[placeholder*="7 天复习"]')
  await expect(goal).toBeVisible()
  await goal.fill(`完成 ${courseName}`)
  await page.getByText('请选择课程', { exact: true }).click()
  await page.getByText(courseName, { exact: true }).last().click()
  await page.getByRole('combobox', { name: '截止日期' }).fill('2026-12-31')
  const created = page.waitForResponse((response) =>
    response.url().endsWith('/api/v1/plans')
    && response.request().method() === 'POST'
    && response.ok(),
  )
  await page.getByRole('button', { name: '生成并保存计划' }).click()
  await created
  await expect(page.getByText('阶段任务', { exact: true })).toBeVisible()
}

async function answerQuiz(page: Page, pass: boolean) {
  const nav = page.locator('.question-nav .qnav-btn')
  await expect(nav.first()).toBeVisible({ timeout: 60_000 })
  const count = await nav.count()
  for (let index = 0; index < count; index += 1) {
    await nav.nth(index).click()
    const card = page.locator('.question-card').last()
    await expect(card).toBeVisible()
    if (await card.getByRole('textbox').count()) {
      await card.getByRole('textbox').fill(pass ? '核心概念 TCP IP HTTP' : '无关答案')
    } else if (await card.locator('input[type="checkbox"]').count()) {
      const choices = card.locator('input[type="checkbox"]')
      if (pass) {
        await choices.nth(0).check()
        await choices.nth(1).check()
      } else {
        await choices.last().check()
      }
    } else {
      const choices = card.locator('input[type="radio"]')
      await (pass ? choices.first() : choices.last()).check()
    }
  }
  const submitted = page.waitForResponse((response) =>
    /\/api\/v1\/quizzes\/\d+\/submit$/.test(response.url())
    && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '提交测验' }).click()
  expect((await submitted).ok()).toBeTruthy()
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

async function createQuizThroughUi(page: Page, courseId: number, options: { pureMultiple?: boolean } = {}) {
  await page.goto(`/quizzes?course_id=${courseId}`)
  await page.getByRole('button', { name: '生成测验' }).click()
  const dialog = page.getByRole('dialog', { name: '生成测验' })
  const numbers = dialog.getByRole('spinbutton')
  await numbers.nth(0).fill(options.pureMultiple ? '2' : '4')
  await numbers.nth(1).fill(options.pureMultiple ? '0' : '1')
  await numbers.nth(2).fill(options.pureMultiple ? '2' : '2')
  await numbers.nth(3).fill(options.pureMultiple ? '0' : '1')
  await numbers.nth(4).fill('75')
  if (options.pureMultiple) {
    await dialog.getByText('单选题', { exact: true }).click()
    await dialog.getByText('判断题', { exact: true }).click()
    await dialog.getByText('简答题', { exact: true }).click()
  }
  const queued = page.waitForResponse((response) =>
    response.url().endsWith('/api/v1/quizzes/generation-jobs')
    && response.request().method() === 'POST'
    && response.ok(),
  )
  await dialog.getByRole('button', { name: '生成', exact: true }).click()
  const job = await (await queued).json()
  expect(Number(job.id)).toBeGreaterThan(0)
  const quizId = await waitForQuizGeneration(page, Number(job.id))
  await expect(page.locator('.question-nav .qnav-btn').first()).toBeVisible({ timeout: 60_000 })
  return quizId
}

test('V7.4.4-E2E-01: registration is independently browser-visible', async ({ page }, testInfo) => {
  const username = await registerThroughUi(page, 'auth')
  await expect(page.getByRole('heading', { name: '仪表盘' })).toBeVisible()
  await expect(page.locator('body')).toContainText(username)
  await saveFinalScreenshot(page, testInfo)
})

test('V7.4.4-E2E-02: material provenance is inspectable through the UI', async ({ page }, testInfo) => {
  await registerThroughUi(page, 'material')
  const course = await prepareCourse(page, 'material')
  await page.goto(`/courses/${course.id}/materials`)
  await page.getByRole('button', { name: '查看片段' }).first().click()
  await expect(page.getByRole('dialog')).toContainText('片段列表')
  await page.getByRole('dialog').locator('.el-dialog__headerbtn').click()
  await page.locator('input[placeholder="输入关键词检索课程资料片段"]').fill('TCP/IP')
  await page.getByRole('button', { name: '检索' }).click()
  await expect(page.getByText('检索结果')).toBeVisible()
  await saveFinalScreenshot(page, testInfo)
})

test('V7.4.4-E2E-03: four-type quiz contract, count, pass line, and result are visible', async ({ page }, testInfo) => {
  await registerThroughUi(page, 'quiz-contract')
  const course = await prepareCourse(page, 'quiz-contract')
  await createQuizThroughUi(page, course.id)
  const nav = page.locator('.question-nav .qnav-btn')
  await expect(nav).toHaveCount(4)
  for (const [index, label] of ['选择题', '多选题', '判断题', '简答题'].entries()) {
    await nav.nth(index).click()
    await expect(page.locator('.question-card').last().getByText(label, { exact: true })).toBeVisible()
  }
  await answerQuiz(page, true)
  await expect(page.getByText('测验通过', { exact: true })).toBeVisible()
  await expect(page.getByText('及格线：75%', { exact: false })).toBeVisible()
  await saveFinalScreenshot(page, testInfo)
})

test('V7.4.4-E2E-04: pure multiple-choice quiz is answered and passed through the UI', async ({ page }, testInfo) => {
  await registerThroughUi(page, 'multiple-choice')
  const course = await prepareCourse(page, 'multiple-choice')
  await createQuizThroughUi(page, course.id, { pureMultiple: true })
  await expect(page.locator('.question-card').first().getByText('多选题', { exact: true })).toBeVisible()
  await expect(page.locator('.question-card input[type="checkbox"]')).toHaveCount(4)
  await answerQuiz(page, true)
  await expect(page.getByText('测验通过', { exact: true })).toBeVisible()
  await saveFinalScreenshot(page, testInfo)
})

test('V7.4.4-E2E-05: failed task quiz retries with a new quiz and then completes', async ({ page }, testInfo) => {
  await registerThroughUi(page, 'retry')
  const course = await prepareCourse(page, 'retry')
  await createPlan(page, course.name)
  const firstQueued = page.waitForResponse((response) =>
    /\/plans\/tasks\/\d+\/quiz-generation-job$/.test(response.url())
    && response.request().method() === 'POST'
    && response.ok(),
  )
  await page.getByRole('button', { name: '生成测验' }).first().click()
  const firstJob = await (await firstQueued).json()
  expect(Number(firstJob.id)).toBeGreaterThan(0)
  const firstQuizId = await waitForQuizGeneration(page, Number(firstJob.id))
  await expect(page).toHaveURL(/\/quizzes/)
  await answerQuiz(page, false)
  await expect(page.getByText('测验未通过', { exact: true })).toBeVisible()
  await page.goto('/plans')
  await expect(page.getByRole('button', { name: '重新练习' })).toBeVisible()
  const retryStarted = page.waitForResponse((response) =>
    /\/plans\/tasks\/\d+\/retry$/.test(response.url()) && response.request().method() === 'POST' && response.ok(),
  )
  await page.getByRole('button', { name: '重新练习' }).click()
  const secondQuizId = Number((await (await retryStarted).json()).quiz_id)
  expect(secondQuizId).toBeGreaterThan(0)
  expect(secondQuizId).not.toBe(firstQuizId)
  await expect(page).toHaveURL(/\/quizzes/)
  await answerQuiz(page, true)
  await expect(page.getByText('测验通过', { exact: true })).toBeVisible()
  await page.goto('/plans')
  await expect(page.getByText('已完成', { exact: true }).first()).toBeVisible()
  await expect(page.getByText(/已完成：\d+ 条/)).toBeVisible()
  await saveFinalScreenshot(page, testInfo)
})

test('V7.4.4-E2E-06: historical KP generation is read-only while sources remain usable', async ({ page }, testInfo) => {
  await registerThroughUi(page, 'history')
  const course = await prepareCourse(page, 'history')
  await page.goto(`/courses/${course.id}/outline`)
  await page.getByRole('button', { name: '重新生成知识点' }).click()
  await page.getByRole('button', { name: '归档并生成' }).click()
  await expect(page.getByText('生成历史')).toBeVisible({ timeout: 60_000 })
  await page.getByText('第 1 版', { exact: true }).click()
  await expect(page.getByText('只读历史模式')).toBeVisible()
  await expect(page.getByRole('button', { name: '生成知识点' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '完成本次复习' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /开始复习任务/ })).toHaveCount(0)
  const urlBeforeCardClick = page.url()
  await page.locator('.kp-card').first().click()
  await expect(page).toHaveURL(urlBeforeCardClick)
  await page.getByRole('button', { name: /查看 .* 的来源片段/ }).first().click()
  await expect(page.getByRole('dialog')).toContainText('来源片段')
  await saveFinalScreenshot(page, testInfo)
})

test('V7.4.4-E2E-07: reschedule history reopens and exposes a stable unscheduled key', async ({ page }, testInfo) => {
  await registerThroughUi(page, 'reschedule')
  const course = await prepareCourse(page, 'reschedule')
  await page.goto('/plans/multi')
  await page.getByRole('row', { name: new RegExp(course.name) }).locator('.el-checkbox').click()
  const tomorrow = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString().slice(0, 10)
  await page.locator('.config-area input[placeholder="选择截止日期"]').fill(tomorrow)
  await page.locator('.constraint-area input').fill('10')
  await page.getByRole('button', { name: '生成综合计划' }).click()
  await expect(page.getByText('未排期', { exact: false }).first()).toBeVisible({ timeout: 60_000 })
  await page.getByRole('button', { name: '重新调度' }).click()
  await page.getByRole('dialog', { name: '重新调度' }).getByRole('button', { name: '重新调度' }).click()
  const diff = page.getByRole('dialog', { name: '重排差异对比' })
  await expect(diff).toBeVisible()
  const unscheduledSection = diff.getByText('未排程', { exact: false }).first().locator('xpath=../..')
  await expect(unscheduledSection).toBeVisible()
  await expect(unscheduledSection.locator('.stable-task-key').first()).not.toHaveText('—')
  await diff.getByRole('button', { name: '关闭' }).click()
  await page.getByRole('button', { name: '历史记录' }).click()
  await expect(page.getByText('重排批次')).toBeVisible()
  await page.getByRole('button', { name: '查看差异' }).click()
  const savedUnscheduled = page.getByRole('dialog', { name: '重排差异对比' }).getByText('未排程', { exact: false }).first().locator('xpath=../..')
  await expect(savedUnscheduled.locator('.stable-task-key').first()).not.toHaveText('—')
  await saveFinalScreenshot(page, testInfo)
})

test('V7.4.4-E2E-08: execution history blocks deletion and the UI archives the plan', async ({ page }, testInfo) => {
  await registerThroughUi(page, 'archive')
  const course = await prepareCourse(page, 'archive')
  await page.goto('/plans/multi')
  await page.getByRole('row', { name: new RegExp(course.name) }).locator('.el-checkbox').click()
  await page.getByRole('button', { name: '生成综合计划' }).click()
  await expect(page.getByRole('button', { name: '重新调度' })).toBeVisible({ timeout: 60_000 })
  await page.goto('/plans')
  const evidenceRecorded = page.waitForResponse((response) =>
    /\/plans\/tasks\/\d+\/events$/.test(response.url()) && response.request().method() === 'POST' && response.ok(),
  )
  await page.getByRole('button', { name: '开始学习' }).click()
  await evidenceRecorded
  await expect(page).toHaveURL(/\/learn/)
  await page.goto('/plans/multi')
  await page.getByText('选择要查看的计划', { exact: true }).click()
  await page.getByText('多课程学习计划', { exact: true }).last().click()
  await expect(page.getByRole('button', { name: '删除计划' })).toBeVisible()
  await page.getByRole('button', { name: '删除计划' }).click()
  await page.getByRole('dialog', { name: '删除计划' }).getByRole('button', { name: '删除' }).click()
  await expect(page.getByRole('dialog', { name: '归档计划' })).toBeVisible()
  await page.getByRole('dialog', { name: '归档计划' }).getByRole('button', { name: '归档' }).click()
  await expect(page.getByText('多课程计划已归档')).toBeVisible()
  await saveFinalScreenshot(page, testInfo)
})
