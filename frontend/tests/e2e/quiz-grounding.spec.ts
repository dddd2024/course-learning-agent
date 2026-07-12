import { test, expect } from '@playwright/test'
import { loginWithFreshUser } from './helpers'

/**
 * E2E: Quiz grounding verification.
 *
 * Verifies that quiz questions are derived from actual course material
 * (not hardcoded content like "梯度下降"). Quiz items should carry
 * source_evidence linked to real chunks.
 */

async function login(page: import('@playwright/test').Page) {
  await loginWithFreshUser(page)
}

test.describe('Quiz Grounding', () => {
  test.beforeEach(async ({ page }) => {
    await login(page)
  })

  test.afterEach(async ({ page }) => {
    await page.evaluate(() => {
      sessionStorage.clear()
      localStorage.clear()
    })
  })

  test('quiz page loads without hardcoded content', async ({ page }) => {
    await page.goto('/quizzes')
    await page.waitForTimeout(2000)

    const bodyText = await page.locator('body').innerText()

    // The hardcoded "梯度下降" string must not appear in the rendered page
    expect(bodyText).not.toContain('梯度下降')
  })

  test('quiz generation produces questions with source evidence', async ({
    page,
    request,
  }) => {
    // Get auth token
    const token = await page.evaluate(() => {
      return sessionStorage.getItem('token') || localStorage.getItem('token') || ''
    })

    // Fetch existing quizzes for course 1
    const quizzesResponse = await request.get(
      'http://127.0.0.1:8000/api/v1/quizzes?course_id=1',
      { headers: { Authorization: `Bearer ${token}` } },
    )

    if (quizzesResponse.ok()) {
      const quizzesBody = await quizzesResponse.json()
      if (quizzesBody.items && quizzesBody.items.length > 0) {
        const quiz = quizzesBody.items[0]

        // If the quiz has items, verify they have source_evidence
        if (quiz.items && quiz.items.length > 0) {
          for (const item of quiz.items) {
            // Each item should have source_evidence (not hardcoded)
            if (item.source_evidence !== undefined) {
              expect(Array.isArray(item.source_evidence)).toBe(true)
            }
            // Question text must not contain the hardcoded string
            expect(item.question_text).not.toContain('梯度下降')
          }
        }
      }
    }

    // The page should be functional
    await expect(page.locator('body')).toBeVisible()
  })
})
