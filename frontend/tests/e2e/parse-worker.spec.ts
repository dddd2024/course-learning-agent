import { test, expect } from '@playwright/test'
import {
  API_BASE,
  registerUniqueUser,
  uploadMaterial,
  waitForMaterialProcessed,
} from './helpers'

/**
 * V6-70: Parse Worker E2E.
 *
 * Verifies the async parse job lifecycle:
 *   1. Upload a material → status "uploaded"
 *   2. POST /parse → response status "processing"
 *   3. Material status becomes "processing" immediately
 *   4. Poll until the parse worker processes the job
 *   5. Material status becomes "ready" (or "failed" with error)
 *   6. Verify chunks were created via the chunks API (total > 0)
 *
 * The parse worker is started by ``playwright.config.ts`` as a
 * ``webServer`` entry (see ``scripts/start_parse_worker_with_health.py``).
 */

const FIXTURE_PDF = 'tests/fixtures/networking-two-column.pdf'

test.describe('Parse Worker (V6)', () => {
  test('parse job lifecycle: queued → processing → ready', async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000)

    // ------------------------------------------------------------------
    // Setup: register and create a course
    // ------------------------------------------------------------------
    const { headers } = await registerUniqueUser(page, request, 'parse')
    const courseName = `E2E-Parse-${Date.now()}`
    const courseRes = await request.post(`${API_BASE}/courses`, {
      headers,
      data: { name: courseName },
    })
    expect(courseRes.ok()).toBeTruthy()
    const courseId = (await courseRes.json()).id

    // ------------------------------------------------------------------
    // 1. Upload material — status should be "uploaded"
    // ------------------------------------------------------------------
    const materialId = await uploadMaterial(
      request,
      headers,
      courseId,
      FIXTURE_PDF,
      'networking-two-column.pdf',
      'application/pdf',
    )

    // Verify the initial material status is "uploaded"
    const materialsBefore = await request.get(
      `${API_BASE}/courses/${courseId}/materials`,
      { headers },
    )
    expect(materialsBefore.ok()).toBeTruthy()
    const materialsBeforeBody = await materialsBefore.json()
    const materialBefore = materialsBeforeBody.items.find(
      (m: { id: number }) => m.id === materialId,
    )
    expect(materialBefore).toBeTruthy()
    expect(materialBefore.status).toBe('uploaded')
    expect(materialBefore.filename).toBe('networking-two-column.pdf')

    // ------------------------------------------------------------------
    // 2. POST /parse — response should indicate "processing"
    // ------------------------------------------------------------------
    const parseRes = await request.post(`${API_BASE}/materials/${materialId}/parse`, {
      headers,
    })
    expect(parseRes.ok()).toBeTruthy()
    const parseBody = await parseRes.json()
    expect(parseBody.material_id).toBe(materialId)
    expect(parseBody.status).toBe('processing')

    // ------------------------------------------------------------------
    // 3. Verify material status is "processing" immediately after parse
    // ------------------------------------------------------------------
    const materialsAfterParse = await request.get(
      `${API_BASE}/courses/${courseId}/materials`,
      { headers },
    )
    expect(materialsAfterParse.ok()).toBeTruthy()
    const materialsAfterParseBody = await materialsAfterParse.json()
    const materialAfterParse = materialsAfterParseBody.items.find(
      (m: { id: number }) => m.id === materialId,
    )
    expect(materialAfterParse.status).toBe('processing')

    // ------------------------------------------------------------------
    // 4. Poll until the material reaches "ready" or "failed"
    // ------------------------------------------------------------------
    let finalStatus = ''
    await expect.poll(
      async () => {
        const res = await request.get(
          `${API_BASE}/courses/${courseId}/materials`,
          { headers },
        )
        if (!res.ok()) return `HTTP ${res.status()}`
        const body = await res.json()
        const material = body.items.find((m: { id: number }) => m.id === materialId)
        finalStatus = material?.status || 'missing'
        return finalStatus
      },
      { timeout: 90_000, intervals: [1_000, 2_000, 3_000] },
    ).not.toBe('processing')

    // ------------------------------------------------------------------
    // 5. Verify the final status and chunks
    // ------------------------------------------------------------------
    expect(['ready', 'failed']).toContain(finalStatus)

    const materialsFinal = await request.get(
      `${API_BASE}/courses/${courseId}/materials`,
      { headers },
    )
    expect(materialsFinal.ok()).toBeTruthy()
    const materialsFinalBody = await materialsFinal.json()
    const materialFinal = materialsFinalBody.items.find(
      (m: { id: number }) => m.id === materialId,
    )
    expect(materialFinal.status).toBe(finalStatus)

    if (finalStatus === 'ready') {
      // Verify chunks were created via the chunks API
      // (MaterialResponse does not include chunk_count)
      const chunksRes = await request.get(
        `${API_BASE}/materials/${materialId}/chunks?page=1&page_size=1`,
        { headers },
      )
      expect(chunksRes.ok()).toBeTruthy()
      const chunksBody = await chunksRes.json()
      expect(chunksBody.total).toBeGreaterThan(0)
      expect(chunksBody.items.length).toBeGreaterThan(0)
      expect(chunksBody.items[0].text).toBeTruthy()
    } else {
      // If parse failed, verify error message is present
      expect(materialFinal.error_message).toBeTruthy()
      expect(typeof materialFinal.error_message).toBe('string')
      expect(materialFinal.error_message.length).toBeGreaterThan(0)
    }
  })

  test('duplicate parse request returns same job without error', async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000)

    const { headers } = await registerUniqueUser(page, request, 'parse2')
    const courseName = `E2E-Parse2-${Date.now()}`
    const courseRes = await request.post(`${API_BASE}/courses`, {
      headers,
      data: { name: courseName },
    })
    expect(courseRes.ok()).toBeTruthy()
    const courseId = (await courseRes.json()).id

    const materialId = await uploadMaterial(
      request,
      headers,
      courseId,
      FIXTURE_PDF,
      'networking-two-column.pdf',
      'application/pdf',
    )

    // First parse request
    const parse1Res = await request.post(`${API_BASE}/materials/${materialId}/parse`, {
      headers,
    })
    expect(parse1Res.ok()).toBeTruthy()
    const parse1Body = await parse1Res.json()
    expect(parse1Body.status).toBe('processing')

    // Second parse request (should return same job, not error)
    const parse2Res = await request.post(`${API_BASE}/materials/${materialId}/parse`, {
      headers,
    })
    expect(parse2Res.ok()).toBeTruthy()
    const parse2Body = await parse2Res.json()
    expect(parse2Body.status).toBe('processing')

    // Wait for parse to complete (ready or failed)
    const finalStatus = await waitForMaterialProcessed(request, headers, courseId, materialId, 90_000)
    expect(['ready', 'failed']).toContain(finalStatus)

    // Verify material final state
    const materialsRes = await request.get(
      `${API_BASE}/courses/${courseId}/materials`,
      { headers },
    )
    expect(materialsRes.ok()).toBeTruthy()
    const materialsBody = await materialsRes.json()
    const material = materialsBody.items.find(
      (m: { id: number }) => m.id === materialId,
    )
    expect(material.status).toBe(finalStatus)

    if (finalStatus === 'ready') {
      // Verify chunks exist via the chunks API
      const chunksRes = await request.get(
        `${API_BASE}/materials/${materialId}/chunks?page=1&page_size=1`,
        { headers },
      )
      expect(chunksRes.ok()).toBeTruthy()
      const chunksBody = await chunksRes.json()
      expect(chunksBody.total).toBeGreaterThan(0)
    }
  })

  test.afterEach(async ({ page }) => {
    await page.evaluate(() => {
      sessionStorage.clear()
      localStorage.clear()
    })
  })
})
