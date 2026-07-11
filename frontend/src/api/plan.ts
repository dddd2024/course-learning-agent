import request from './index'
import type { AxiosPromise } from 'axios'

export type TodoStatus = 'pending' | 'completed' | 'postponed'

export type TaskStatus = 'pending' | 'in_progress' | 'completed'

export interface PlanGoal {
  id: number
  title: string
  deadline: string
  daily_minutes: number
  status: string
}

export interface PlanTask {
  id: number
  goal_id: number
  course_id: number
  course_name: string
  title: string
  task_type: string
  estimate_minutes: number
  priority: number
  acceptance: string | null
  status: string
}

export interface Todo {
  id: number
  user_id: number
  task_id: number
  course_id: number
  course_name: string
  title: string
  scheduled_date: string
  scheduled_start: string | null
  scheduled_end: string | null
  estimate_minutes: number
  status: TodoStatus
  actual_minutes: number | null
  completed_at: string | null
}

export interface PlanPayload {
  goal: string
  course_ids: number[]
  /** Legacy compatibility for older callers; new UI code uses stable ids. */
  courses?: string[]
  deadline: string
  daily_minutes: number
}

export interface PlanResult {
  goal: PlanGoal
  tasks: PlanTask[]
  todos: Todo[]
  unscheduled_tasks?: Array<{ title: string; estimate_minutes: number; reason: string; suggestion: string }>
}

export interface PlanProgress {
  tasks_total: number
  tasks_completed: number
  todos_total: number
  todos_completed: number
}

export interface PlanSummary {
  goal: PlanGoal
  course_ids: number[]
  course_names: string[]
  progress: PlanProgress
  created_at: string
  updated_at: string
}

export interface PlanListResult {
  items: PlanSummary[]
  total: number
}

export interface TodoListParams {
  date?: string
  status?: TodoStatus
  course_id?: number
  page?: number
  page_size?: number
}

export interface TodoListResult {
  items: Todo[]
  total: number
}

export interface TodoUpdatePayload {
  status?: TodoStatus
  actual_minutes?: number
}

export function createPlan(payload: PlanPayload): AxiosPromise<PlanResult> {
  return request.post('/plans', payload)
}

export function listPlans(): AxiosPromise<PlanListResult> {
  return request.get('/plans')
}

export function getPlan(id: number): AxiosPromise<PlanResult> {
  return request.get(`/plans/${id}`)
}

export interface MultiPlanCourseInput {
  course_id: number
  deadline: string
  user_priority?: number
}

export interface MultiPlanConstraints {
  [key: string]: unknown
}

export interface MultiPlanPayload {
  courses: MultiPlanCourseInput[]
  daily_minutes: number
  constraints?: MultiPlanConstraints
}

export interface MultiPlanScheduleItem {
  scheduled_date: string
  course_name: string
  title: string
  estimate_minutes: number
  start_time: string | null
  end_time: string | null
}

export interface MultiPlanResult {
  schedule: MultiPlanScheduleItem[]
  overflow_warnings: string[]
}

export function createMultiPlan(payload: MultiPlanPayload): AxiosPromise<MultiPlanResult> {
  return request.post('/plans/multi', payload)
}

export function listTodos(params?: TodoListParams): AxiosPromise<TodoListResult> {
  return request.get('/todos', { params })
}

export function updateTodo(id: number, payload: TodoUpdatePayload): AxiosPromise<Todo> {
  return request.patch(`/todos/${id}`, payload)
}

export interface TaskUpdatePayload {
  status?: string
}

export function updateTask(id: number, payload: TaskUpdatePayload): AxiosPromise<PlanTask> {
  return request.patch(`/plans/tasks/${id}`, payload)
}

export interface GoalUpdatePayload {
  status?: string
}

export function updateGoal(id: number, payload: GoalUpdatePayload): AxiosPromise<PlanGoal> {
  return request.patch(`/plans/${id}`, payload)
}

export function deletePlan(id: number): AxiosPromise<void> {
  return request.delete(`/plans/${id}`)
}
