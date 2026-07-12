import { test, expect } from '@playwright/test'
import {
  API_BASE,
  registerUniqueUser,
  setupCourseWithMaterialAndKPs,
} from './helpers'

/**
 * V6-70: Multi-Plan Lifecycle E2E.
 *
 * Tests the full CRUD lifecycle of a multi-course plan:
 *   POST /plans/multi      → create
 *   GET  /plans/multi/{id}  → read
 *   PATCH /plans/multi/{id} → update status
 *   DELETE /plans/multi/{id} → delete
 *   GET  /plans/multi/{id}  → 404 after deletion
 *
 * Strong assertions verify specific field values at each step.
 */

const FIXTURE_PDF = 'tests/fixtures/networking-two-column.pdf'

test.describe('Multi-Plan Lifecycle (V6)', () => {
  test('create → get → patch → delete → 404', async ({ page, request }) => {
    test.setTimeout(120_000)

    // ------------------------------------------------------------------
    // Setup: register user, create 2 courses with materials + KPs
    // ------------------------------------------------------------------
    const { headers } = await registerUniqueUser(page, request, 'mp')

    const course1Name = `E2E-MP1-${Date.now()}`
    const { courseId: courseId1, kpCount: kp1 } = await setupCourseWithMaterialAndKPs(
      request,
      headers,
      course1Name,
      FIXTURE_PDF,
      'networking-two-column.pdf',
      'application/pdf',
    )
    expect(kp1).toBeGreaterThan(0)

    const course2Name = `E2E-MP2-${Date.now()}`
    const { courseId: courseId2, kpCount: kp2 } = await setupCourseWithMaterialAndKPs(
      request,
      headers,
      course2Name,
      FIXTURE_PDF,
      'networking-two-column.pdf',
      'application/pdf',
    )
    expect(kp2).toBeGreaterThan(0)

    // ------------------------------------------------------------------
    // POST /plans/multi — create a multi-course plan
    // ------------------------------------------------------------------
    const createRes = await request.post(`${API_BASE}/plans/multi`, {
      headers,
      data: {
        courses: [
          { course_id: courseId1, deadline: '2026-12-31', user_priority: 0.8 },
          { course_id: courseId2, deadline: '2026-12-31', user_priority: 0.6 },
        ],
        daily_minutes: 120,
      },
    })
    expect(createRes.ok()).toBeTruthy()
    const createBody = await createRes.json()

    // Strong assertions on the create response
    expect(createBody.multi_plan_id).toBeGreaterThan(0)
    const multiPlanId = createBody.multi_plan_id
    expect(createBody.schedule).toBeDefined()
    expect(Array.isArray(createBody.schedule)).toBe(true)
    expect(createBody.schedule.length).toBeGreaterThan(0)

    // Each schedule item must have specific non-empty fields
    for (const item of createBody.schedule) {
      expect(item.title).toBeTruthy()
      expect(typeof item.title).toBe('string')
      expect(item.title.length).toBeGreaterThan(0)
      expect(item.estimate_minutes).toBeGreaterThan(0)
      expect(item.scheduled_date).toBeTruthy()
    }

    // ------------------------------------------------------------------
    // GET /plans/multi/{id} — read the multi-plan detail
    // ------------------------------------------------------------------
    const getRes = await request.get(`${API_BASE}/plans/multi/${multiPlanId}`, {
      headers,
    })
    expect(getRes.ok()).toBeTruthy()
    const detail = await getRes.json()

    // Strong assertions on the detail response
    expect(detail.id).toBe(multiPlanId)
    expect(detail.title).toBeTruthy()
    expect(typeof detail.title).toBe('string')
    expect(detail.title.length).toBeGreaterThan(0)
    expect(detail.status).toBe('active')
    expect(detail.deadline).toBeTruthy()
    expect(detail.daily_minutes).toBe(120)
    expect(detail.tasks).toBeDefined()
    expect(Array.isArray(detail.tasks)).toBe(true)
    expect(detail.tasks.length).toBeGreaterThan(0)

    // Each task item should have a course_id
    for (const task of detail.tasks) {
      expect(task.course_id).toBeGreaterThan(0)
      expect([courseId1, courseId2]).toContain(task.course_id)
      expect(task.estimate_minutes).toBeGreaterThanOrEqual(0)
    }

    // ------------------------------------------------------------------
    // PATCH /plans/multi/{id} — update the status to "archived"
    // ------------------------------------------------------------------
    const patchRes = await request.patch(`${API_BASE}/plans/multi/${multiPlanId}`, {
      headers,
      data: { status: 'archived' },
    })
    expect(patchRes.ok()).toBeTruthy()
    const patched = await patchRes.json()

    // Strong assertion: status changed to "archived"
    expect(patched.id).toBe(multiPlanId)
    expect(patched.status).toBe('archived')
    expect(patched.daily_minutes).toBe(120)

    // ------------------------------------------------------------------
    // PATCH again — change status to "done"
    // ------------------------------------------------------------------
    const patch2Res = await request.patch(`${API_BASE}/plans/multi/${multiPlanId}`, {
      headers,
      data: { status: 'done' },
    })
    expect(patch2Res.ok()).toBeTruthy()
    const patched2 = await patch2Res.json()
    expect(patched2.status).toBe('done')

    // ------------------------------------------------------------------
    // DELETE /plans/multi/{id} — delete the multi-plan
    // ------------------------------------------------------------------
    const deleteRes = await request.delete(`${API_BASE}/plans/multi/${multiPlanId}`, {
      headers,
    })
    expect(deleteRes.status()).toBe(204)

    // ------------------------------------------------------------------
    // GET /plans/multi/{id} — verify 404 after deletion
    // ------------------------------------------------------------------
    const getAfterDeleteRes = await request.get(
      `${API_BASE}/plans/multi/${multiPlanId}`,
      { headers },
    )
    expect(getAfterDeleteRes.status()).toBe(404)
  })

  test.afterEach(async ({ page }) => {
    await page.evaluate(() => {
      sessionStorage.clear()
      localStorage.clear()
    })
  })
})
