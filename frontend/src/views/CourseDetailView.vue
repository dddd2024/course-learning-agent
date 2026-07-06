<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Document, ChatDotRound, Collection } from '@element-plus/icons-vue'
import { getCourse, type Course } from '../api/course'
import { parseApiError } from '../utils/error'

const route = useRoute()
const router = useRouter()

const course = ref<Course | null>(null)
const loading = ref(false)

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

onMounted(() => {
  fetchCourse()
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
        <h2 class="info-name">{{ course.name }}</h2>
        <div class="info-meta">
          <span v-if="course.teacher">教师：{{ course.teacher }}</span>
          <span v-if="course.semester">学期：{{ course.semester }}</span>
        </div>
        <div v-if="course.description" class="info-desc">{{ course.description }}</div>
      </div>
    </el-card>

    <div v-if="course" class="entries">
      <el-card class="entry-card" shadow="hover" @click="goToMaterials">
        <el-icon :size="32"><Document /></el-icon>
        <div class="entry-title">资料</div>
        <div class="entry-desc">课程文件与资料管理</div>
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

.entries {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
}

.entry-card {
  cursor: pointer;
  text-align: center;
  padding: 8px 0;
}

.entry-card :deep(.el-card__body) {
  padding: 24px 16px;
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
