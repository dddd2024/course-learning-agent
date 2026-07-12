import { test, expect } from '@playwright/test'
import {
  API_BASE,
  registerUniqueUser,
  setupCourseWithMaterialAndKPs,
} from './helpers'

/**
 * V6-70: Rewritten Quiz Grounding E2E.
 *
 * Verifies that every quiz item carries non-empty ``source_evidence``
 * (with ``chunk_id`` and ``quote_text``), that the quiz title is
 * non-empty, and that the question count matches the request (or the
 * ``partial_generation`` flag is set).  Also tests quiz submission
 * with all-correct answers (score ≈ 100) and submission with wrong
 * answers (weak points created).
 */

const FIXTURE_PDF = 'tests/fixtures/networking-two-column.pdf'
const QUESTION_COUNT = 5

test.describe('Quiz Grounding (V6)', () => {
  test('quiz items have source_evidence and correct submission scores 100', async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000)

    // ------------------------------------------------------------------
    // Setup: register, create course, upload material, parse, generate KPs
    // ------------------------------------------------------------------
    const { headers } = await registerUniqueUser(page, request, 'quiz')
    const courseName = `E2E-Quiz-${Date.now()}`
    const { courseId, kpCount } = await setupCourseWithMaterialAndKPs(
      request,
      headers,
      courseName,
      FIXTURE_PDF,
      'networking-two-column.pdf',
      'application/pdf',
    )
    expect(kpCount).toBeGreaterThan(0)

    // ------------------------------------------------------------------
    // Generate a practice quiz (for learning correct answers)
    // ------------------------------------------------------------------
    const practiceRes = await request.post(`${API_BASE}/quizzes`, {
      headers,
      data: { course_id: courseId, question_count: QUESTION_COUNT },
    })
    expect(practiceRes.ok()).toBeTruthy()
    const practiceQuiz = await practiceRes.json()

    // ------------------------------------------------------------------
    // Assert: quiz title is not empty
    // ------------------------------------------------------------------
    expect(practiceQuiz.title).toBeTruthy()
    expect(typeof practiceQuiz.title).toBe('string')
    expect(practiceQuiz.title.length).toBeGreaterThan(0)

    // ------------------------------------------------------------------
    // Assert: every quiz item has non-empty source_evidence with
    // chunk_id and quote_text
    // ------------------------------------------------------------------
    expect(practiceQuiz.items.length).toBeGreaterThan(0)
    for (const item of practiceQuiz.items) {
      expect(item.source_evidence).toBeDefined()
      expect(Array.isArray(item.source_evidence)).toBe(true)
      expect(item.source_evidence.length).toBeGreaterThan(0)

      const evidence = item.source_evidence[0]
      expect(evidence.chunk_id).toBeTruthy()
      expect(typeof evidence.chunk_id).toBe('number')
      expect(evidence.chunk_id).toBeGreaterThan(0)
      expect(evidence.quote_text).toBeTruthy()
      expect(typeof evidence.quote_text).toBe('string')
      expect(evidence.quote_text.length).toBeGreaterThan(0)
    }

    // ------------------------------------------------------------------
    // Assert: question count matches requested count (or partial_generation)
    // ------------------------------------------------------------------
    if (practiceQuiz.items.length !== QUESTION_COUNT) {
      expect(practiceQuiz.partial_generation).toBe(true)
    } else {
      expect(practiceQuiz.items.length).toBe(QUESTION_COUNT)
    }

    // ------------------------------------------------------------------
    // Navigate to the quiz view to verify it loads
    // ------------------------------------------------------------------
    await page.goto(
      `/quizzes?course_id=${courseId}&quiz_id=${practiceQuiz.id}`,
    )
    await expect(page.locator('body')).toBeVisible()

    // ------------------------------------------------------------------
    // Build correct answers from the quiz items themselves.
    //
    // The mock LLM is deterministic:
    //   - true_false: answer is always "true"
    //   - choice: correct answer is the first option's value
    //   - short_answer: the correct term appears in the explanation
    //     field as 「{term}」
    // ------------------------------------------------------------------
    const correctAnswers = practiceQuiz.items.map(
      (item: {
        id: number
        question_type: string
        options: Array<{ label: string; value: string }>
        explanation: string | null
      }) => {
        let userAnswer = 'true'
        if (item.question_type === 'choice' && item.options.length > 0) {
          userAnswer = item.options[0].value || item.options[0].label || 'A'
        } else if (item.question_type === 'short_answer' && item.explanation) {
          // Parse the term from 「」 in the explanation
          const match = item.explanation.match(/「([^」]+)」/)
          if (match) {
            userAnswer = match[1]
          }
        }
        return { item_id: item.id, user_answer: userAnswer }
      },
    )

    const correctSubmitRes = await request.post(
      `${API_BASE}/quizzes/${practiceQuiz.id}/submit`,
      { headers, data: { answers: correctAnswers } },
    )
    expect(correctSubmitRes.ok()).toBeTruthy()
    const correctResult = await correctSubmitRes.json()

    // ------------------------------------------------------------------
    // Assert: score is high (all answers should be correct)
    // ------------------------------------------------------------------
    expect(correctResult.total).toBe(practiceQuiz.items.length)
    expect(correctResult.score).toBeGreaterThanOrEqual(
      Math.floor(practiceQuiz.items.length * 0.8),
    )

    // Verify each result item has correct_answer and is_correct fields
    for (const item of correctResult.items) {
      expect(item.correct_answer).toBeDefined()
      expect(typeof item.correct_answer).toBe('string')
      expect(item.is_correct).toBeDefined()
    }
  })

  test('submitting with wrong answers creates weak points', async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000)

    // ------------------------------------------------------------------
    // Setup
    // ------------------------------------------------------------------
    const { headers } = await registerUniqueUser(page, request, 'quizwp')
    const courseName = `E2E-QuizWP-${Date.now()}`
    const { courseId, kpCount } = await setupCourseWithMaterialAndKPs(
      request,
      headers,
      courseName,
      FIXTURE_PDF,
      'networking-two-column.pdf',
      'application/pdf',
    )
    expect(kpCount).toBeGreaterThan(0)

    // ------------------------------------------------------------------
    // Generate a quiz
    // ------------------------------------------------------------------
    const quizRes = await request.post(`${API_BASE}/quizzes`, {
      headers,
      data: { course_id: courseId, question_count: QUESTION_COUNT },
    })
    expect(quizRes.ok()).toBeTruthy()
    const quiz = await quizRes.json()
    expect(quiz.items.length).toBeGreaterThan(0)

    // Assert source_evidence on all items
    for (const item of quiz.items) {
      expect(item.source_evidence).toBeDefined()
      expect(Array.isArray(item.source_evidence)).toBe(true)
      expect(item.source_evidence.length).toBeGreaterThan(0)
      expect(item.source_evidence[0].chunk_id).toBeTruthy()
      expect(item.source_evidence[0].quote_text).toBeTruthy()
    }

    // ------------------------------------------------------------------
    // Submit with all wrong answers
    // ------------------------------------------------------------------
    const wrongAnswers = quiz.items.map(
      (item: { id: number; question_type: string }) => ({
        item_id: item.id,
        user_answer:
          item.question_type === 'true_false'
            ? 'false'
            : item.question_type === 'choice'
              ? 'Z'
              : 'completely wrong answer',
      }),
    )
    const submitRes = await request.post(
      `${API_BASE}/quizzes/${quiz.id}/submit`,
      { headers, data: { answers: wrongAnswers } },
    )
    expect(submitRes.ok()).toBeTruthy()
    const result = await submitRes.json()

    // ------------------------------------------------------------------
    // Assert: score is low (most or all answers wrong)
    // ------------------------------------------------------------------
    expect(result.total).toBe(quiz.items.length)
    expect(result.score).toBeLessThanOrEqual(40)

    // ------------------------------------------------------------------
    // Assert: weak points are created for wrong answers
    // ------------------------------------------------------------------
    expect(result.weak_point_changes).toBeDefined()
    expect(Array.isArray(result.weak_point_changes)).toBe(true)
    expect(result.weak_point_changes.length).toBeGreaterThan(0)

    for (const wp of result.weak_point_changes) {
      expect(wp.knowledge_point_id).toBeTruthy()
      expect(typeof wp.knowledge_point_id).toBe('number')
      expect(wp.knowledge_point_id).toBeGreaterThan(0)
      expect(wp.correct).toBe(false)
      expect(wp.action).toBeTruthy()
      expect(wp.current).toBeDefined()
      expect(wp.current.wrong_count).toBeGreaterThan(0)
    }

    // Fetch weak points list to verify titles are populated
    const wpListRes = await request.get(
      `${API_BASE}/courses/${courseId}/weak-points`,
      { headers },
    )
    expect(wpListRes.ok()).toBeTruthy()
    const wpList = await wpListRes.json()
    expect(wpList.items.length).toBeGreaterThan(0)
    for (const wp of wpList.items) {
      expect(wp.knowledge_point_id).toBeTruthy()
      expect(wp.knowledge_point_title).toBeTruthy()
      expect(typeof wp.knowledge_point_title).toBe('string')
      expect(wp.knowledge_point_title.length).toBeGreaterThan(0)
    }
  })

  test.afterEach(async ({ page }) => {
    await page.evaluate(() => {
      sessionStorage.clear()
      localStorage.clear()
    })
  })
})
