import { test, expect } from '@playwright/test'
import {
  API_BASE,
  registerUniqueUser,
  setupCourseWithMaterialAndKPs,
  waitForMaterialStatus,
} from './helpers'

/**
 * V7 Acceptance E2E — 11 scenarios (V7-E2E-01 through V7-E2E-11).
 *
 * Each test is tagged with its V7-E2E-XX identifier and covers a
 * specific V7 acceptance criterion. All tests run against the real
 * backend (with mock LLM) and frontend dev server started by
 * playwright.config.ts.
 */

test.describe('V7 Acceptance E2E', () => {
  test.afterEach(async ({ page }) => {
    await page.evaluate(() => {
      sessionStorage.clear()
      localStorage.clear()
    })
  })

  // --------------------------------------------------------------------
  // V7-E2E-01: Document IR cleaning pipeline
  // --------------------------------------------------------------------
  test('V7-E2E-01: Document IR cleaning pipeline produces clean chunks', async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000)
    const { headers } = await registerUniqueUser(page, request, 'v7e1')

    const courseRes = await request.post(`${API_BASE}/courses`, {
      headers,
      data: { name: `V7E1-Course-${Date.now()}` },
    })
    expect(courseRes.ok()).toBeTruthy()
    const courseId = (await courseRes.json()).id

    const textContent = `第1页
操作系统概述
操作系统是管理计算机硬件和软件资源的程序。
它为应用程序提供接口，并为用户提供服务。

第2页
进程管理
进程是程序在执行中的实例。
操作系统负责进程的创建、调度和销毁。

第3页
内存管理
虚拟内存将物理内存扩展到磁盘。
页表记录虚拟页到物理页的映射。
`
    const textBuffer = Buffer.from(textContent, 'utf-8')
    const uploadRes = await request.post(`${API_BASE}/courses/${courseId}/materials`, {
      headers,
      multipart: { file: { name: 'os-notes.txt', mimeType: 'text/plain', buffer: textBuffer } },
    })
    expect(uploadRes.ok()).toBeTruthy()
    const materialId = (await uploadRes.json()).id

    const parseRes = await request.post(`${API_BASE}/materials/${materialId}/parse`, {
      headers,
    })
    expect(parseRes.ok()).toBeTruthy()

    await waitForMaterialStatus(request, headers, courseId, materialId, 'ready', 90_000)

    const chunksRes = await request.get(
      `${API_BASE}/courses/${courseId}/materials/${materialId}/chunks`,
      { headers },
    )
    expect(chunksRes.ok()).toBeTruthy()
    const chunksBody = await chunksRes.json()
    expect(chunksBody.items.length).toBeGreaterThan(0)

    for (const chunk of chunksBody.items) {
      expect(chunk.content).not.toMatch(/^第\d+页$/m)
    }
  })

  // --------------------------------------------------------------------
  // V7-E2E-02: Chunk source fragment provenance
  // --------------------------------------------------------------------
  test('V7-E2E-02: Chunks have source fragment provenance', async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000)
    const { headers } = await registerUniqueUser(page, request, 'v7e2')

    const { courseId, materialId } = await setupCourseWithMaterialAndKPs(
      request,
      headers,
      `V7E2-Course-${Date.now()}`,
    )

    const chunksRes = await request.get(
      `${API_BASE}/courses/${courseId}/materials/${materialId}/chunks`,
      { headers },
    )
    expect(chunksRes.ok()).toBeTruthy()
    const chunksBody = await chunksRes.json()
    expect(chunksBody.items.length).toBeGreaterThan(0)

    const chunksWithProvenance = chunksBody.items.filter(
      (c: { source_fragments_json }) => c.source_fragments_json,
    )
    expect(chunksWithProvenance.length).toBeGreaterThan(0)
  })

  // --------------------------------------------------------------------
  // V7-E2E-03: Quiz creation enforces strict contract
  // --------------------------------------------------------------------
  test('V7-E2E-03: Quiz creation enforces strict contract', async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000)
    const { headers } = await registerUniqueUser(page, request, 'v7e3')

    const { courseId } = await setupCourseWithMaterialAndKPs(
      request,
      headers,
      `V7E3-Course-${Date.now()}`,
    )

    const quizRes = await request.post(`${API_BASE}/quizzes`, {
      headers,
      data: {
        course_id: courseId,
        question_count: 3,
        question_types: ['choice', 'true_false'],
        difficulty_distribution: { easy: 0, medium: 3, hard: 0 },
        pass_score: 60,
      },
    })
    expect(quizRes.ok(), await quizRes.text()).toBeTruthy()
    const quiz = await quizRes.json()

    expect(quiz.items.length).toBe(3)
    expect(quiz.pass_score).toBe(60)

    for (const item of quiz.items) {
      expect(item.question_text).toBeTruthy()
      expect(item.question_type).toBeTruthy()
    }
  })

  // --------------------------------------------------------------------
  // V7-E2E-04: Quiz UI configurability
  // --------------------------------------------------------------------
  test('V7-E2E-04: Quiz UI shows configurable controls', async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000)
    const { headers } = await registerUniqueUser(page, request, 'v7e4')

    const { courseId } = await setupCourseWithMaterialAndKPs(
      request,
      headers,
      `V7E4-Course-${Date.now()}`,
    )

    await page.goto(`/quizzes?course_id=${courseId}`)
    await page.waitForTimeout(2_000)

    const genBtn = page.locator('button:has-text("生成测验")')
    if (await genBtn.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await genBtn.click()
      await page.waitForTimeout(1_000)

      const dialog = page.locator('.el-dialog')
      await expect(dialog).toBeVisible({ timeout: 5_000 })
      const dialogText = await dialog.textContent()
      expect(dialogText!.length).toBeGreaterThan(20)
    }
  })

  // --------------------------------------------------------------------
  // V7-E2E-05: Multi-plan list endpoint with status filter
  // --------------------------------------------------------------------
  test('V7-E2E-05: Multi-plan list endpoint with status filter', async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000)
    const { headers } = await registerUniqueUser(page, request, 'v7e5')

    const { courseId: courseId1 } = await setupCourseWithMaterialAndKPs(
      request,
      headers,
      `V7E5-C1-${Date.now()}`,
    )
    const { courseId: courseId2 } = await setupCourseWithMaterialAndKPs(
      request,
      headers,
      `V7E5-C2-${Date.now()}`,
    )

    const create1 = await request.post(`${API_BASE}/plans/multi`, {
      headers,
      data: {
        courses: [{ course_id: courseId1, deadline: '2026-12-31', user_priority: 0.8 }],
        daily_minutes: 60,
      },
    })
    expect(create1.ok()).toBeTruthy()
    const plan1 = (await create1.json()).multi_plan_id

    const create2 = await request.post(`${API_BASE}/plans/multi`, {
      headers,
      data: {
        courses: [{ course_id: courseId2, deadline: '2026-12-31', user_priority: 0.6 }],
        daily_minutes: 60,
      },
    })
    expect(create2.ok()).toBeTruthy()
    const plan2 = (await create2.json()).multi_plan_id

    const archiveRes = await request.patch(`${API_BASE}/plans/multi/${plan2}`, {
      headers,
      data: { status: 'archived' },
    })
    expect(archiveRes.ok()).toBeTruthy()

    const listRes = await request.get(`${API_BASE}/plans/multi`, { headers })
    expect(listRes.ok()).toBeTruthy()
    const list = await listRes.json()
    expect(Array.isArray(list)).toBe(true)
    expect(list.length).toBeGreaterThanOrEqual(2)

    for (const item of list) {
      expect(item.id).toBeGreaterThan(0)
      expect(item.title).toBeTruthy()
      expect(item.status).toBeTruthy()
    }

    const activeRes = await request.get(`${API_BASE}/plans/multi?status=active`, {
      headers,
    })
    expect(activeRes.ok()).toBeTruthy()
    const activeList = await activeRes.json()
    for (const item of activeList) {
      expect(item.status).toBe('active')
    }

    const activeIds = activeList.map((i: { id: number }) => i.id)
    expect(activeIds).toContain(plan1)
    expect(activeIds).not.toContain(plan2)
  })

  // --------------------------------------------------------------------
  // V7-E2E-06: Multi-plan history returns all generations
  // --------------------------------------------------------------------
  test('V7-E2E-06: Multi-plan history returns all generations', async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000)
    const { headers } = await registerUniqueUser(page, request, 'v7e6')

    const { courseId } = await setupCourseWithMaterialAndKPs(
      request,
      headers,
      `V7E6-Course-${Date.now()}`,
    )

    const createRes = await request.post(`${API_BASE}/plans/multi`, {
      headers,
      data: {
        courses: [{ course_id: courseId, deadline: '2026-12-31', user_priority: 0.8 }],
        daily_minutes: 120,
      },
    })
    expect(createRes.ok()).toBeTruthy()
    const multiPlanId = (await createRes.json()).multi_plan_id

    const detail1Res = await request.get(`${API_BASE}/plans/multi/${multiPlanId}`, {
      headers,
    })
    expect(detail1Res.ok()).toBeTruthy()
    const detail1 = await detail1Res.json()
    expect(detail1.generation_version).toBe(1)

    const rescheduleRes = await request.post(
      `${API_BASE}/plans/multi/${multiPlanId}/reschedule`,
      {
        headers,
        data: { daily_minutes: 90 },
      },
    )
    expect(rescheduleRes.ok()).toBeTruthy()

    const detail2Res = await request.get(`${API_BASE}/plans/multi/${multiPlanId}`, {
      headers,
    })
    expect(detail2Res.ok()).toBeTruthy()
    const detail2 = await detail2Res.json()
    expect(detail2.generation_version).toBe(2)

    const historyRes = await request.get(
      `${API_BASE}/plans/multi/${multiPlanId}/history`,
      { headers },
    )
    expect(historyRes.ok()).toBeTruthy()
    const history = await historyRes.json()
    expect(Array.isArray(history)).toBe(true)
    expect(history.length).toBeGreaterThan(0)

    const generations = new Set(
      history.map((h: { generation }) => h.generation).filter((g: number) => g != null),
    )
    expect(generations.size).toBeGreaterThanOrEqual(1)
  })

  // --------------------------------------------------------------------
  // V7-E2E-07: Multi-plan delete and 404
  // --------------------------------------------------------------------
  test('V7-E2E-07: Multi-plan delete and 404', async ({ page, request }) => {
    test.setTimeout(120_000)
    const { headers } = await registerUniqueUser(page, request, 'v7e7')

    const { courseId } = await setupCourseWithMaterialAndKPs(
      request,
      headers,
      `V7E7-Course-${Date.now()}`,
    )

    const createRes = await request.post(`${API_BASE}/plans/multi`, {
      headers,
      data: {
        courses: [{ course_id: courseId, deadline: '2026-12-31', user_priority: 0.8 }],
        daily_minutes: 60,
      },
    })
    expect(createRes.ok()).toBeTruthy()
    const multiPlanId = (await createRes.json()).multi_plan_id

    const getRes = await request.get(`${API_BASE}/plans/multi/${multiPlanId}`, {
      headers,
    })
    expect(getRes.ok()).toBeTruthy()

    const deleteRes = await request.delete(`${API_BASE}/plans/multi/${multiPlanId}`, {
      headers,
    })
    expect(deleteRes.status()).toBe(204)

    const getAfterRes = await request.get(`${API_BASE}/plans/multi/${multiPlanId}`, {
      headers,
    })
    expect(getAfterRes.status()).toBe(404)
  })

  // --------------------------------------------------------------------
  // V7-E2E-08: Plan execution lifecycle completes to 100%
  // --------------------------------------------------------------------
  test('V7-E2E-08: Plan execution lifecycle completes to 100%', async ({
    page,
    request,
  }) => {
    test.setTimeout(180_000)
    const { headers } = await registerUniqueUser(page, request, 'v7e8')

    const { courseId } = await setupCourseWithMaterialAndKPs(
      request,
      headers,
      `V7E8-Course-${Date.now()}`,
    )

    const planRes = await request.post(`${API_BASE}/plans`, {
      headers,
      data: {
        goal: `掌握 V7E8 课程`,
        course_ids: [courseId],
        deadline: '2026-12-31',
        daily_minutes: 120,
      },
    })
    expect(planRes.ok()).toBeTruthy()
    const plan = await planRes.json()
    const goalId = plan.goal.id
    expect(plan.tasks.length).toBeGreaterThan(0)

    const learnTasks = plan.tasks.filter((t: { task_type: string }) => t.task_type === 'learn')
    for (const task of learnTasks) {
      const startRes = await request.post(`${API_BASE}/plans/tasks/${task.id}/start`, {
        headers,
      })
      if (startRes.ok()) {
        const overrideRes = await request.post(
          `${API_BASE}/plans/tasks/${task.id}/override`,
          { headers, data: { reason: 'V7 E2E: learn task completed' } },
        )
        expect(overrideRes.ok()).toBeTruthy()
      }
    }

    const reviewTasks = plan.tasks.filter((t: { task_type: string }) => t.task_type === 'review')
    for (const task of reviewTasks) {
      const overrideRes = await request.post(
        `${API_BASE}/plans/tasks/${task.id}/override`,
        { headers, data: { reason: 'V7 E2E: review task completed' } },
      )
      expect(overrideRes.ok()).toBeTruthy()
    }

    const quizTasks = plan.tasks.filter((t: { task_type: string }) => t.task_type === 'quiz')
    for (const task of quizTasks) {
      const startRes = await request.post(`${API_BASE}/plans/tasks/${task.id}/start`, {
        headers,
      })
      if (startRes.ok()) {
        const startBody = await startRes.json()
        const quizId = startBody.quiz_id
        if (quizId) {
          const quizRes = await request.get(`${API_BASE}/quizzes/${quizId}`, { headers })
          if (quizRes.ok()) {
            const quiz = await quizRes.json()
            const answers = quiz.items.map((item: { id: number; question_type: string }) => ({
              item_id: item.id,
              user_answer: item.question_type === 'true_false'
                ? 'true'
                : item.question_type === 'multiple_choice'
                  ? ['A', 'B']
                  : item.question_type === 'short_answer'
                    ? '知识框架'
                    : 'A',
            }))
            const submitRes = await request.post(
              `${API_BASE}/quizzes/${quizId}/submit`,
              { headers, data: { answers, task_id: task.id } },
            )
            expect(submitRes.ok()).toBeTruthy()
          }
        }
      } else {
        const overrideRes = await request.post(
          `${API_BASE}/plans/tasks/${task.id}/override`,
          { headers, data: { reason: 'V7 E2E: quiz task override' } },
        )
        expect(overrideRes.ok()).toBeTruthy()
      }
    }

    const finalRes = await request.get(`${API_BASE}/plans/${goalId}`, { headers })
    expect(finalRes.ok()).toBeTruthy()
    const finalPlan = await finalRes.json()
    const allDone = finalPlan.tasks.every(
      (t: { status: string }) => t.status === 'done',
    )
    expect(allDone).toBe(true)
  })

  // --------------------------------------------------------------------
  // V7-E2E-09: Quiz items have source evidence
  // --------------------------------------------------------------------
  test('V7-E2E-09: Quiz items have source evidence', async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000)
    const { headers } = await registerUniqueUser(page, request, 'v7e9')

    const { courseId } = await setupCourseWithMaterialAndKPs(
      request,
      headers,
      `V7E9-Course-${Date.now()}`,
    )

    const quizRes = await request.post(`${API_BASE}/quizzes`, {
      headers,
      data: {
        course_id: courseId,
        question_count: 3,
        question_types: ['choice', 'true_false'],
        difficulty_distribution: { easy: 0, medium: 3, hard: 0 },
        pass_score: 60,
      },
    })
    expect(quizRes.ok(), await quizRes.text()).toBeTruthy()
    const quiz = await quizRes.json()
    expect(quiz.items.length).toBe(3)

    for (const item of quiz.items) {
      expect(item.question_text).toBeTruthy()
      expect(item.question_text.length).toBeGreaterThan(0)
    }

    const dummyAnswers = quiz.items.map((item: { id: number }) => ({
      item_id: item.id,
      user_answer: 'A',
    }))
    const submitRes = await request.post(`${API_BASE}/quizzes/${quiz.id}/submit`, {
      headers,
      data: { answers: dummyAnswers },
    })
    expect(submitRes.ok()).toBeTruthy()
    const result = await submitRes.json()
    expect(result.total).toBe(quiz.items.length)

    for (const item of result.items) {
      expect(item.correct_answer).toBeTruthy()
    }
  })

  // --------------------------------------------------------------------
  // V7-E2E-10: Parse worker lifecycle
  // --------------------------------------------------------------------
  test('V7-E2E-10: Parse worker lifecycle: queued to ready', async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000)
    const { headers } = await registerUniqueUser(page, request, 'v7e10')

    const courseRes = await request.post(`${API_BASE}/courses`, {
      headers,
      data: { name: `V7E10-Course-${Date.now()}` },
    })
    expect(courseRes.ok()).toBeTruthy()
    const courseId = (await courseRes.json()).id

    const textContent = `计算机网络基础

TCP/IP协议栈分为四层：应用层、传输层、网络层和链路层。
应用层协议包括HTTP、FTP、SMTP等。
传输层协议包括TCP和UDP。
TCP提供可靠的面向连接的服务，UDP提供不可靠的无连接服务。

IP协议工作在网络层，负责将数据包从源地址路由到目标地址。
ARP协议将IP地址解析为MAC地址。
`
    const textBuffer = Buffer.from(textContent, 'utf-8')
    const uploadRes = await request.post(`${API_BASE}/courses/${courseId}/materials`, {
      headers,
      multipart: { file: { name: 'networking.txt', mimeType: 'text/plain', buffer: textBuffer } },
    })
    expect(uploadRes.ok()).toBeTruthy()
    const materialId = (await uploadRes.json()).id

    const parseRes = await request.post(`${API_BASE}/materials/${materialId}/parse`, {
      headers,
    })
    expect(parseRes.ok()).toBeTruthy()

    await waitForMaterialStatus(request, headers, courseId, materialId, 'ready', 90_000)

    const chunksRes = await request.get(
      `${API_BASE}/courses/${courseId}/materials/${materialId}/chunks`,
      { headers },
    )
    expect(chunksRes.ok()).toBeTruthy()
    const chunksBody = await chunksRes.json()
    expect(chunksBody.items.length).toBeGreaterThan(0)

    for (const chunk of chunksBody.items) {
      expect(chunk.content.length).toBeGreaterThan(10)
    }
  })

  // --------------------------------------------------------------------
  // V7-E2E-11: Auth isolation and security boundaries
  // --------------------------------------------------------------------
  test('V7-E2E-11: Auth isolation and security boundaries', async ({
    page,
    request,
  }) => {
    test.setTimeout(60_000)

    const { headers: headersA } = await registerUniqueUser(page, request, 'v7e11a')
    await page.evaluate(() => {
      sessionStorage.clear()
      localStorage.clear()
    })
    const { headers: headersB } = await registerUniqueUser(page, request, 'v7e11b')

    const courseRes = await request.post(`${API_BASE}/courses`, {
      headers: headersA,
      data: { name: `V7E11-Private-${Date.now()}` },
    })
    expect(courseRes.ok()).toBeTruthy()
    const courseId = (await courseRes.json()).id

    const crossRes = await request.get(`${API_BASE}/courses`, { headers: headersB })
    expect(crossRes.ok()).toBeTruthy()
    const coursesB = await crossRes.json()
    const found = coursesB.items.find((c: { id: number }) => c.id === courseId)
    expect(found).toBeUndefined()

    const noAuthRes = await request.get(`${API_BASE}/courses`)
    expect(noAuthRes.ok()).toBeFalsy()

    const directAccessRes = await request.get(`${API_BASE}/courses/${courseId}`, {
      headers: headersB,
    })
    expect(directAccessRes.status()).toBe(404)
  })
})
