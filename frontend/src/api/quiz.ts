import request from './index'
import type { AxiosPromise } from 'axios'

export type QuestionType = 'choice' | 'multiple_choice' | 'true_false' | 'short_answer'
export interface QuizOption { label: string; text: string; value: string }
export type QuizStatus = 'draft' | 'submitted'

export interface QuizItem {
  id: number
  question_type: QuestionType
  question_text: string
  options: QuizOption[]
  explanation: string
  order_index: number
}

export interface Quiz {
  id: number
  course_id: number
  title: string
  question_count: number
  status: QuizStatus
  score: number | null
  created_at: string
  items: QuizItem[]
}

export interface QuizListResult {
  items: Quiz[]
  total?: number
}

export interface QuizSubmitAnswer {
  item_id: number
  user_answer: string | string[]
}

export interface QuizSubmitPayload {
  answers: QuizSubmitAnswer[]
}

export interface QuizResultItem {
  id: number
  question_text: string
  question_type: QuestionType
  options: QuizOption[]
  correct_answer: string
  user_answer: string | string[]
  is_correct: boolean
  explanation: string
  knowledge_point_id: number | null
  rubric_feedback: Array<{ criterion: string; met: boolean; keywords: string[]; message: string }>
  needs_review: boolean
}

export interface QuizResult {
  id: number
  score: number
  total: number
  items: QuizResultItem[]
}

export interface WeakPoint {
  id: number
  course_id: number
  knowledge_point_id: number
  knowledge_point_title: string
  wrong_count: number
  last_wrong_at: string | null
}

export interface WeakPointListResult {
  items: WeakPoint[]
}

export function createQuiz(
  courseId: number,
  knowledgePointIds?: number[],
  questionCount?: number,
): AxiosPromise<Quiz> {
  const payload: Record<string, unknown> = { course_id: courseId }
  if (knowledgePointIds && knowledgePointIds.length > 0) {
    payload.knowledge_point_ids = knowledgePointIds
  }
  if (questionCount !== undefined) {
    payload.question_count = questionCount
  }
  return request.post('/quizzes', payload)
}

export function getQuizzes(
  courseId?: number,
  params?: { page?: number; page_size?: number },
): AxiosPromise<QuizListResult> {
  const query: Record<string, unknown> = {}
  if (courseId !== undefined) {
    query.course_id = courseId
  }
  if (params?.page !== undefined) {
    query.page = params.page
  }
  if (params?.page_size !== undefined) {
    query.page_size = params.page_size
  }
  return request.get('/quizzes', { params: query })
}

export function getQuiz(id: number): AxiosPromise<Quiz> {
  return request.get(`/quizzes/${id}`)
}

export function getQuizResult(id: number): AxiosPromise<QuizResult> {
  return request.get(`/quizzes/${id}/result`)
}

export function deleteQuiz(id: number): AxiosPromise<void> {
  return request.delete(`/quizzes/${id}`)
}

export function submitQuiz(
  id: number,
  answers: QuizSubmitAnswer[],
): AxiosPromise<QuizResult> {
  return request.post(`/quizzes/${id}/submit`, { answers })
}

export function getWeakPoints(courseId: number): AxiosPromise<WeakPointListResult> {
  return request.get(`/courses/${courseId}/weak-points`)
}
