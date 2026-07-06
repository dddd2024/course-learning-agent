import request from './index'
import type { AxiosPromise } from 'axios'

/** 仪表盘汇总数据（6 项聚合计数，均按当前用户隔离）。 */
export interface DashboardSummary {
  course_count: number
  material_count: number
  knowledge_point_count: number
  todo_today_count: number
  todo_completed_count: number
  agent_run_count: number
}

export function getDashboardSummary(): AxiosPromise<DashboardSummary> {
  return request.get('/dashboard/summary')
}
