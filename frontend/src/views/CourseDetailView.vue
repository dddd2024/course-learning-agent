<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ChatDotRound,
  Collection,
  Connection,
  Document,
  Reading,
  Calendar,
  EditPen,
} from '@element-plus/icons-vue'
import { getCourse, type Course } from '../api/course'
import { listMaterials } from '../api/material'
import { listKnowledgePoints } from '../api/knowledge'
import { parseApiError } from '../utils/error'

const route = useRoute()
const router = useRouter()

const course = ref<Course | null>(null)
const loading = ref(false)
const materialsCount = ref<number | null>(null)
const knowledgePointsCount = ref<number | null>(null)

async function fetchCourse() {
  const id = Number(route.params.id)
  if (!id) {
    ElMessage.error('课程 ID 无效')
    router.push('/courses')
    return
  }
  loading.value = true
  try {
    const { data } = await getCourse(id)
    course.value = data
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取课程详情失败'))
    router.push('/courses')
  } finally {
    loading.value = false
  }
}

function goBack() {
  router.push('/courses')
}

function goToMaterials() {
  router.push(`/courses/${route.params.id}/materials`)
}

function goToChat() {
  router.push(`/courses/${route.params.id}/chat`)
}

function goToOutline() {
  router.push(`/courses/${route.params.id}/outline`)
}

function goToLearn() {
  router.push(`/courses/${route.params.id}/learn`)
}

function goToKnowledgeGraph() {
  router.push('/knowledge-graph')
}

function goToPlans() {
  router.push('/plans')
}

function goToQuizzes() {
  router.push('/quizzes')
}

async function fetchCounts() {
  const id = Number(route.params.id)
  if (!id) return
  try {
    const [{ data: materialsData }, { data: kpData }] = await Promise.all([
      listMaterials(id),
      listKnowledgePoints(id),
    ])
    materialsCount.value = materialsData.total
    knowledgePointsCount.value = kpData.total
  } catch {
    // 计数仅为辅助展示，失败时静默忽略，不影响主流程
  }
}

onMounted(async () => {
  await fetchCourse()
  if (course.value) {
    fetchCounts()
  }
})
</script>

<template>
  <div v-loading="loading" class="page">
    <div class="header">
      <el-button @click="goBack">返回课程列表</el-button>
    </div>

    <el-card v-if="course" class="info-card">
      <div class="color-bar" :style="{ backgroundColor: course.color || '#409eff' }" />
      <div class="info-body">
        <div class="info-header">
          <div>
            <h2 class="info-name">{{ course.name }}</h2>
            <div class="info-meta">
              <span v-if="course.teacher">教师：{{ course.teacher }}</span>
              <span v-if="course.semester">学期：{{ course.semester }}</span>
            </div>
            <div v-if="course.description" class="info-desc">{{ course.description }}</div>
          </div>
          <div class="info-stats">
            <div class="info-stat">
              <span class="info-stat-value">{{ materialsCount ?? '-' }}</span>
              <span class="info-stat-label">资料</span>
            </div>
            <div class="info-stat-divider" />
            <div class="info-stat">
              <span class="info-stat-value">{{ knowledgePointsCount ?? '-' }}</span>
              <span class="info-stat-label">知识点</span>
            </div>
          </div>
        </div>
      </div>
    </el-card>

    <div v-if="course" class="entries">
      <el-card class="entry-card" shadow="hover" @click="goToMaterials">
        <el-icon :size="32"><Document /></el-icon>
        <div class="entry-title">资料</div>
        <div class="entry-desc">课程文件与资料管理</div>
        <div v-if="materialsCount !== null" class="entry-badge">
          {{ materialsCount }}
        </div>
      </el-card>
      <el-card class="entry-card" shadow="hover" @click="goToChat">
        <el-icon :size="32"><ChatDotRound /></el-icon>
        <div class="entry-title">问答</div>
        <div class="entry-desc">智能问答与答疑</div>
      </el-card>
      <el-card class="entry-card" shadow="hover" @click="goToOutline">
        <el-icon :size="32"><Collection /></el-icon>
        <div class="entry-title">知识点</div>
        <div class="entry-desc">知识点体系梳理</div>
        <div v-if="knowledgePointsCount !== null" class="entry-badge">
          {{ knowledgePointsCount }}
        </div>
      </el-card>
      <el-card class="entry-card" shadow="hover" @click="goToLearn">
        <el-icon :size="32"><Reading /></el-icon>
        <div class="entry-title">文档学习</div>
        <div class="entry-desc">沉浸式文档阅读学习</div>
      </el-card>
      <el-card class="entry-card" shadow="hover" @click="goToPlans">
        <el-icon :size="32"><Calendar /></el-icon>
        <div class="entry-title">学习计划</div>
        <div class="entry-desc">制定课程学习计划</div>
      </el-card>
      <el-card class="entry-card" shadow="hover" @click="goToQuizzes">
        <el-icon :size="32"><EditPen /></el-icon>
        <div class="entry-title">测验</div>
        <div class="entry-desc">知识点测验与自测</div>
      </el-card>
      <el-card class="entry-card" shadow="hover" @click="goToKnowledgeGraph">
        <el-icon :size="32"><Connection /></el-icon>
        <div class="entry-title">知识图谱</div>
        <div class="entry-desc">课程知识图谱可视化</div>
      </el-card>
    </div>
  </div>
</template>

<style scoped>
.page {
  background: #fff;
  padding: 24px;
  border-radius: 4px;
}

.header {
  margin-bottom: 16px;
}

.info-card {
  margin-bottom: 24px;
}

.info-card :deep(.el-card__body) {
  padding: 0;
}

.color-bar {
  height: 6px;
}

.info-body {
  padding: 20px;
}

.info-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.info-name {
  font-size: 22px;
  margin: 0 0 12px;
  color: #303133;
}

.info-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 14px;
  color: #606266;
  margin-bottom: 12px;
}

.info-desc {
  font-size: 14px;
  color: #909399;
  line-height: 1.6;
}

.info-stats {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 20px;
  background: #f5f7fa;
  border-radius: 8px;
  flex-shrink: 0;
}

.info-stat {
  text-align: center;
}

.info-stat-value {
  display: block;
  font-size: 24px;
  font-weight: 700;
  color: #409eff;
  line-height: 1.2;
}

.info-stat-label {
  display: block;
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}

.info-stat-divider {
  width: 1px;
  height: 32px;
  background: #e6e6e6;
}

.entries {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
}

.entry-card {
  cursor: pointer;
  text-align: center;
  padding: 8px 0;
  position: relative;
}

.entry-card :deep(.el-card__body) {
  padding: 24px 16px;
}

.entry-badge {
  position: absolute;
  top: 12px;
  right: 12px;
  min-width: 22px;
  height: 22px;
  padding: 0 7px;
  border-radius: 11px;
  background: #409eff;
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  line-height: 22px;
  text-align: center;
  box-sizing: border-box;
}

.entry-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  margin-top: 12px;
}

.entry-desc {
  font-size: 13px;
  color: #909399;
  margin-top: 4px;
}
</style>
