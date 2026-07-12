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
  // PLAN-V3-01: execution fields
  target_type: string | null
  target_id: number | null
  target_spec: Record<string, unknown> | null
  execution_status: string
  verification_method: string | null
  verification_result: Record<string, unknown> | null
  auto_completed_at: string | null
  started_at: string | null
  completed_at: string | null
  last_action_at: string | null
}

export interface TaskStartResult {
  route: string
  params: Record<string, unknown>
  action_type: 'open_material' | 'open_knowledge_point' | 'open_quiz'
  route_name: 'course-learn' | 'course-outline' | 'quizzes'
  route_params: Record<string, unknown>
  target_id: number | null
  quiz_id: number | null
  target_type: string | null
  execution_status?: string
  started_at?: string | null
}

export interface TaskVerifyResult {
  verified: boolean
  verification_result: Record<string, unknown>
  completion_status: string
  execution_status?: string
  status?: string
}

export interface TaskExecutionInfo {
  task_id: number
  target_type: string | null
  target_id: number | null
  target_spec: Record<string, unknown> | null
  execution_status: string
  verification_method: string | null
  verification_result: Record<string, unknown> | null
  auto_completed_at: string | null
  started_at: string | null
  completed_at: string | null
  last_action_at: string | null
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
  multi_plan_id?: number | null
  schedule: MultiPlanScheduleItem[]
  overflow_warnings: string[]
  unscheduled_tasks: Array<{
    course_name: string
    title: string
    estimate_minutes: number
    deadline: string
    remaining_budget: number
    reason: string
    suggestion: string
  }>
}

export function createMultiPlan(payload: MultiPlanPayload): AxiosPromise<MultiPlanResult> {
  return request.post('/plans/multi', payload)
}

// V6-41: Multi-plan lifecycle types & API functions

export interface MultiPlanTaskItem {
  task_id: number | null
  course_id: number
  course_name: string
  title: string
  scheduled_date: string | null
  estimate_minutes: number
  unscheduled_reason: string | null
}

export interface MultiPlanDetail {
  id: number
  title: string
  status: string
  deadline: string
  daily_minutes: number
  tasks: MultiPlanTaskItem[]
}

export function getMultiPlan(id: number): AxiosPromise<MultiPlanDetail> {
  return request.get(`/plans/multi/${id}`)
}

export function patchMultiPlan(
  id: number,
  payload: { status?: string },
): AxiosPromise<MultiPlanDetail> {
  return request.patch(`/plans/multi/${id}`, payload)
}

export function deleteMultiPlan(id: number): AxiosPromise<void> {
  return request.delete(`/plans/multi/${id}`)
}

export function rescheduleMultiPlan(
  id: number,
  payload: { daily_minutes: number },
): AxiosPromise<MultiPlanResult> {
  return request.post(`/plans/multi/${id}/reschedule`, payload)
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

// PLAN-V3-02: Task execution API functions

export function startTask(taskId: number): AxiosPromise<TaskStartResult> {
  return request.post(`/plans/tasks/${taskId}/start`)
}

export function verifyTask(taskId: number, confirmation?: boolean): AxiosPromise<TaskVerifyResult> {
  return request.post(`/plans/tasks/${taskId}/verify`, { confirmation: confirmation ?? null })
}

export function recordTaskEvent(taskId: number, eventType: 'target_loaded' | 'user_confirmed' | 'review_confirmed', targetId: number, materialVersionId?: number): AxiosPromise<{ recorded: boolean }> {
  return request.post(`/plans/tasks/${taskId}/events`, { event_type: eventType, target_id: targetId, material_version_id: materialVersionId })
}

export function retryTask(taskId: number): AxiosPromise<TaskStartResult> {
  return request.post(`/plans/tasks/${taskId}/retry`)
}

export function getExecutionInfo(taskId: number): AxiosPromise<TaskExecutionInfo> {
  return request.get(`/plans/tasks/${taskId}/execution`)
}

export function overrideTask(
  taskId: number,
  reason: string,
): AxiosPromise<TaskVerifyResult> {
  return request.post(`/plans/tasks/${taskId}/override`, { reason })
}
