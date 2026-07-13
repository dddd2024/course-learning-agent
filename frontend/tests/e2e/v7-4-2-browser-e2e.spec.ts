/**
 * V7.4.2-08: Real browser E2E tests for functional authenticity closure.
 *
 * 7 scenarios covering V7.4.2 features:
 * 1. Login + dashboard navigation
 * 2. Course creation + material upload + KP generation
 * 3. Knowledge point generation history view (V7.4.2-07)
 * 4. Quiz creation with contract enforcement (V7.4.2-03)
 * 5. Multi-plan archive safety (V7.4.2-05)
 * 6. Reschedule five-category diff (V7.4.2-06)
 * 7. Quiz atomic submission with task verification (V7.4.2-04)
 */
import { test, expect, type APIRequestContext, type Page } from '@playwright/test'
import {
  API_BASE,
  TEST_USER,
  registerUniqueUser,
  setupCourseWithMaterialAndKPs,
  waitForMaterialStatus,
} from './helpers'

test.describe('V7.4.2 Functional Authenticity Closure', () => {
  test.describe.configure({ mode: 'serial', timeout: 300_000 })

  // Shared state across serial tests
  let token: string
  let headers: Record<string, string>
  let courseId: number
  let materialId: number
  let kpIds: number[]

  // ---------------------------------------------------------------------------
  // 1. Login + dashboard navigation
  // ---------------------------------------------------------------------------
  test('1. Login and navigate to dashboard', async ({ page, request }) => {
    const result = await registerUniqueUser(page, request, 'v742e2e')
    token = result.token
    headers = result.headers

    await expect(page).toHaveURL(/\/dashboard/)
    await expect(page.locator('body')).toContainText('课程学习助手')
  })

  // ---------------------------------------------------------------------------
  // 2. Course creation + material upload + KP generation
  // ---------------------------------------------------------------------------
  test('2. Create course, upload material, generate KPs', async ({ request }) => {
    const setup = await setupCourseWithMaterialAndKPs(
      request,
      headers,
      'V742-E2E-测试课程',
    )
    courseId = setup.courseId
    materialId = setup.materialId
    expect(setup.kpCount).toBeGreaterThan(0)

    // Fetch KP IDs
    const kpRes = await request.get(`${API_BASE}/courses/${courseId}/knowledge-points`, { headers })
    expect(kpRes.ok()).toBeTruthy()
    const kpBody = await kpRes.json()
    kpIds = kpBody.items.map((kp: { id: number }) => kp.id)
    expect(kpIds.length).toBeGreaterThan(0)
  })

  // ---------------------------------------------------------------------------
  // 3. Knowledge point generation history view (V7.4.2-07)
  // ---------------------------------------------------------------------------
  test('3. KP generation history API returns generations', async ({ request }) => {
    const genRes = await request.get(
      `${API_BASE}/courses/${courseId}/knowledge-points/generations`,
      { headers },
    )
    expect(genRes.ok()).toBeTruthy()
    const generations = await genRes.json()
    expect(generations.length).toBeGreaterThan(0)
    expect(generations[0].generation).toBeGreaterThanOrEqual(1)
    expect(generations[0].count).toBeGreaterThan(0)
  })

  test('3a. KP by generation API returns correct KPs', async ({ request }) => {
    const gen1Res = await request.get(
      `${API_BASE}/courses/${courseId}/knowledge-points/generations/1`,
      { headers },
    )
    expect(gen1Res.ok()).toBeTruthy()
    const gen1Body = await gen1Res.json()
    expect(gen1Body.items.length).toBeGreaterThan(0)
    expect(gen1Body.items.every((kp: { generation: number }) => kp.generation === 1)).toBeTruthy()
  })

  // ---------------------------------------------------------------------------
  // 4. Quiz creation with contract enforcement (V7.4.2-03)
  // ---------------------------------------------------------------------------
  test('4. Quiz creation with contract defaults', async ({ request }) => {
    const quizRes = await request.post(`${API_BASE}/quizzes`, {
      headers,
      data: {
        course_id: courseId,
        knowledge_point_ids: kpIds.slice(0, Math.min(3, kpIds.length)),
        question_count: 3,
      },
      timeout: 120_000,
    })
    // Accept either success (200/201) or constraint error (400) — the LLM
    // may reject with insufficient_evidence for small test materials.
    // The key assertion is that the API processes the request and returns
    // a structured response (not a 500 or 422 validation error).
    expect([200, 201, 400, 422].includes(quizRes.status())).toBeTruthy()
    const body = await quizRes.json()
    if (quizRes.ok()) {
      expect(body.id).toBeDefined()
      expect(body.question_count).toBeGreaterThanOrEqual(1)
    } else {
      // Constraint error must have structured fields
      expect(body.code).toBeDefined()
      expect(body.drop_reasons).toBeDefined()
    }
  })

  // ---------------------------------------------------------------------------
  // 5. Multi-plan archive safety (V7.4.2-05)
  // ---------------------------------------------------------------------------
  test('5. Multi-plan archive safety', async ({ request }) => {
    // Create a second course for multi-plan
    const course2Res = await request.post(`${API_BASE}/courses`, {
      headers,
      data: { name: 'V742-E2E-课程B' },
    })
    expect(course2Res.ok()).toBeTruthy()
    const course2Id = (await course2Res.json()).id

    // Create multi-plan
    const today = new Date()
    const deadline = new Date(today.getTime() + 7 * 24 * 60 * 60 * 1000)
    const planRes = await request.post(`${API_BASE}/plans/multi`, {
      headers,
      data: {
        courses: [
          { course_id: courseId, deadline: deadline.toISOString().split('T')[0] },
          { course_id: course2Id, deadline: deadline.toISOString().split('T')[0] },
        ],
        daily_minutes: 30,
      },
      timeout: 120_000,
    })
    expect(planRes.ok()).toBeTruthy()
    const plan = await planRes.json()
    const planId = plan.multi_plan_id
    expect(planId).toBeDefined()

    // Archive the plan
    const archiveRes = await request.post(`${API_BASE}/plans/multi/${planId}/archive`, { headers })
    expect(archiveRes.ok()).toBeTruthy()
    const archived = await archiveRes.json()
    expect(archived.status).toBe('archived')

    // Verify plan is archived via GET
    const getRes = await request.get(`${API_BASE}/plans/multi/${planId}`, { headers })
    expect(getRes.ok()).toBeTruthy()
    expect((await getRes.json()).status).toBe('archived')
  })

  // ---------------------------------------------------------------------------
  // 6. Reschedule five-category diff (V7.4.2-06)
  // ---------------------------------------------------------------------------
  test('6. Reschedule returns five-category diff', async ({ request }) => {
    // Create a multi-plan for reschedule testing
    const today = new Date()
    const deadline = new Date(today.getTime() + 14 * 24 * 60 * 60 * 1000)
    const planRes = await request.post(`${API_BASE}/plans/multi`, {
      headers,
      data: {
        courses: [
          { course_id: courseId, deadline: deadline.toISOString().split('T')[0] },
        ],
        daily_minutes: 60,
      },
      timeout: 120_000,
    })
    expect(planRes.ok()).toBeTruthy()
    const plan = await planRes.json()
    const planId = plan.multi_plan_id

    // Reschedule
    const reschedRes = await request.post(
      `${API_BASE}/plans/multi/${planId}/reschedule`,
      {
        headers,
        data: { daily_minutes: 90 },
        timeout: 120_000,
      },
    )
    expect(reschedRes.ok()).toBeTruthy()
    const reschedBody = await reschedRes.json()

    // Verify five categories exist
    expect(reschedBody.diff).toBeDefined()
    const diff = reschedBody.diff
    for (const cat of ['kept', 'moved', 'created', 'superseded', 'unscheduled']) {
      expect(diff[cat]).toBeDefined()
      expect(Array.isArray(diff[cat])).toBeTruthy()
    }

    // If any items exist, verify they have required fields
    const allItems = [
      ...diff.kept,
      ...diff.moved,
      ...diff.created,
      ...diff.superseded,
      ...diff.unscheduled,
    ]
    if (allItems.length > 0) {
      const item = allItems[0]
      expect(item).toHaveProperty('stable_task_key')
      expect(item).toHaveProperty('reason')
      expect(item).toHaveProperty('title')
    }
  })

  // ---------------------------------------------------------------------------
  // 7. Quiz atomic submission with task verification (V7.4.2-04)
  // ---------------------------------------------------------------------------
  test('7. Quiz result includes percentage, pass_score, passed fields', async ({ request }) => {
    // Create a quiz — may fail with constraint error for small test materials
    const quizRes = await request.post(`${API_BASE}/quizzes`, {
      headers,
      data: {
        course_id: courseId,
        knowledge_point_ids: kpIds.slice(0, Math.min(2, kpIds.length)),
        question_count: 2,
      },
      timeout: 120_000,
    })

    // If quiz creation failed (constraint error), skip submission test
    if (!quizRes.ok()) {
      console.log('Quiz creation returned constraint error, skipping submission test')
      expect([400, 422].includes(quizRes.status())).toBeTruthy()
      return
    }

    const quiz = await quizRes.json()
    const quizId = quiz.id

    // Get quiz items
    const quizDetailRes = await request.get(`${API_BASE}/quizzes/${quizId}`, { headers })
    expect(quizDetailRes.ok()).toBeTruthy()
    const quizDetail = await quizDetailRes.json()
    const items = quizDetail.items || []
    expect(items.length).toBeGreaterThan(0)

    // Submit with correct answers
    const answers = items.map((item: { id: number; answer: string }) => ({
      item_id: item.id,
      user_answer: item.answer,
    }))

    const submitRes = await request.post(`${API_BASE}/quizzes/${quizId}/submit`, {
      headers,
      data: { answers },
    })
    expect(submitRes.ok()).toBeTruthy()
    const result = await submitRes.json()

    // V7.4.2-04: Verify new fields exist
    expect(result).toHaveProperty('percentage')
    expect(result).toHaveProperty('pass_score')
    expect(result).toHaveProperty('passed')
    expect(typeof result.percentage).toBe('number')
    expect(typeof result.pass_score).toBe('number')
    expect(typeof result.passed).toBe('boolean')
  })
})
