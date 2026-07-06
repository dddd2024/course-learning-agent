import request from './index'
import type { AxiosPromise } from 'axios'

export interface Course {
  id: number
  name: string
  teacher: string
  semester: string
  description: string
  color: string
}

export interface CoursePayload {
  name: string
  teacher?: string
  semester?: string
  description?: string
  color?: string
}

export interface CourseListParams {
  page?: number
  page_size?: number
  keyword?: string
}

export interface CourseListResult {
  items: Course[]
  total: number
  page: number
  page_size: number
}

export function listCourses(params?: CourseListParams): AxiosPromise<CourseListResult> {
  return request.get('/courses', { params })
}

export function createCourse(payload: CoursePayload): AxiosPromise<Course> {
  return request.post('/courses', payload)
}

export function getCourse(id: number): AxiosPromise<Course> {
  return request.get(`/courses/${id}`)
}

export function updateCourse(id: number, payload: CoursePayload): AxiosPromise<Course> {
  return request.put(`/courses/${id}`, payload)
}

export function deleteCourse(id: number): AxiosPromise<void> {
  return request.delete(`/courses/${id}`)
}
