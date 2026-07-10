<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  ElMessage,
  ElMessageBox,
  type FormInstance,
  type FormRules,
} from 'element-plus'
import {
  listCourses,
  createCourse,
  updateCourse,
  deleteCourse,
  type Course,
  type CoursePayload,
} from '../api/course'
import { parseApiError } from '../utils/error'
import EmptyState from '../components/common/EmptyState.vue'

const router = useRouter()

const courses = ref<Course[]>([])
const total = ref(0)
const loading = ref(false)
const loadError = ref('')

const query = reactive({
  page: 1,
  page_size: 10,
  keyword: '',
})

const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const dialogLoading = ref(false)
const formRef = ref<FormInstance>()

const defaultForm = (): CoursePayload => ({
  name: '',
  teacher: '',
  semester: '',
  description: '',
  color: '#2563eb',
})

const form = reactive<CoursePayload & { id?: number }>(defaultForm())

const formRules: FormRules<typeof form> = {
  name: [
    { required: true, message: '请输入课程名称', trigger: 'blur' },
    { min: 1, max: 100, message: '课程名称 1-100 字', trigger: 'blur' },
  ],
  description: [
    { max: 500, message: '课程简介不超过 500 字', trigger: 'blur' },
  ],
}

async function fetchCourses() {
  loading.value = true
  loadError.value = ''
  try {
    const { data } = await listCourses({
      page: query.page,
      page_size: query.page_size,
      keyword: query.keyword || undefined,
    })
    courses.value = data.items
    total.value = data.total
  } catch (err) {
    loadError.value = parseApiError(err, '获取课程列表失败')
  } finally {
    loading.value = false
  }
}

let searchTimer: ReturnType<typeof setTimeout> | null = null
function handleSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    query.page = 1
    fetchCourses()
  }, 300)
}

function handlePageChange(page: number) {
  query.page = page
  fetchCourses()
}

function handlePageSizeChange(size: number) {
  query.page_size = size
  query.page = 1
  fetchCourses()
}

function resetForm() {
  Object.assign(form, defaultForm())
  form.id = undefined
}

function openCreate() {
  dialogMode.value = 'create'
  resetForm()
  dialogVisible.value = true
}

function openEdit(course: Course) {
  dialogMode.value = 'edit'
  Object.assign(form, {
    id: course.id,
    name: course.name,
    teacher: course.teacher,
    semester: course.semester,
    description: course.description,
    color: course.color || '#2563eb',
  })
  dialogVisible.value = true
}

async function handleSubmit() {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  dialogLoading.value = true
  const payload: CoursePayload = {
    name: form.name,
    teacher: form.teacher,
    semester: form.semester,
    description: form.description,
    color: form.color,
  }
  try {
    if (dialogMode.value === 'create') {
      await createCourse(payload)
      ElMessage.success('创建成功')
    } else if (form.id !== undefined) {
      await updateCourse(form.id, payload)
      ElMessage.success('更新成功')
    }
    dialogVisible.value = false
    fetchCourses()
  } catch (err) {
    ElMessage.error(parseApiError(err, '保存失败'))
  } finally {
    dialogLoading.value = false
  }
}

async function handleDelete(course: Course) {
  try {
    await ElMessageBox.confirm(
      `确定删除课程「${course.name}」吗？此操作不可恢复。`,
      '删除确认',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  try {
    await deleteCourse(course.id)
    ElMessage.success('删除成功')
    if (courses.value.length === 1 && query.page > 1) {
      query.page -= 1
    }
    fetchCourses()
  } catch (err) {
    ElMessage.error(parseApiError(err, '删除失败'))
  }
}

function goToDetail(course: Course) {
  router.push(`/courses/${course.id}`)
}

onMounted(() => {
  fetchCourses()
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <div>
        <h2 class="title">课程管理</h2>
        <p class="subtitle">课程是资料、问答、计划与测验的共同学习空间</p>
      </div>
      <div class="actions">
        <el-input
          v-model="query.keyword"
          placeholder="搜索课程名称"
          clearable
          class="search-input"
          @input="handleSearchInput"
          @clear="handleSearchInput"
        />
        <el-button type="primary" @click="openCreate">新建课程</el-button>
      </div>
    </div>

    <el-alert
      v-if="loadError"
      :title="loadError"
      type="error"
      show-icon
      :closable="false"
      class="load-error"
    >
      <template #default>
        <el-button size="small" @click="fetchCourses">重新加载</el-button>
      </template>
    </el-alert>

    <div v-if="!loadError" v-loading="loading" class="course-grid">
      <EmptyState
        v-if="!loading && courses.length === 0"
        title="还没有课程"
        description="创建你的第一门课程开始学习吧"
        action-text="新建课程"
        @action="openCreate"
      />
      <el-card
        v-for="course in courses"
        :key="course.id"
        class="course-card"
        shadow="hover"
        role="button"
        tabindex="0"
        :aria-label="`打开课程 ${course.name}`"
        @click="goToDetail(course)"
        @keydown.enter="goToDetail(course)"
        @keydown.space.prevent="goToDetail(course)"
      >
        <div class="card-color" :style="{ backgroundColor: course.color || '#2563eb' }" />
        <div class="card-body">
          <div class="card-name">{{ course.name }}</div>
          <div class="card-meta">
            <span v-if="course.teacher">教师：{{ course.teacher }}</span>
            <span v-if="course.semester">学期：{{ course.semester }}</span>
          </div>
          <div v-if="course.description" class="card-desc">{{ course.description }}</div>
          <div class="card-actions" @click.stop>
            <el-button size="small" @click="openEdit(course)">编辑</el-button>
            <el-button size="small" type="danger" @click="handleDelete(course)">
              删除
            </el-button>
          </div>
        </div>
      </el-card>
    </div>

    <div v-if="total > 0" class="pagination">
      <el-pagination
        background
        layout="total, sizes, prev, pager, next"
        :total="total"
        :current-page="query.page"
        :page-size="query.page_size"
        :page-sizes="[10, 20, 50]"
        @current-change="handlePageChange"
        @size-change="handlePageSizeChange"
      />
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="dialogMode === 'create' ? '新建课程' : '编辑课程'"
      width="520px"
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="formRules"
        label-position="top"
      >
        <el-form-item label="课程名称" prop="name">
          <el-input v-model="form.name" maxlength="100" show-word-limit />
        </el-form-item>
        <el-form-item label="授课教师" prop="teacher">
          <el-input v-model="form.teacher" />
        </el-form-item>
        <el-form-item label="学期" prop="semester">
          <el-input v-model="form.semester" placeholder="如 2025 春季" />
        </el-form-item>
        <el-form-item label="课程简介" prop="description">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            maxlength="500"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="主题色" prop="color">
          <el-color-picker v-model="form.color" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="dialogLoading" @click="handleSubmit">
          确定
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  background: #fff;
  padding: 24px;
  border-radius: 4px;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.title {
  font-size: 20px;
  margin: 0;
  color: #303133;
}

.subtitle {
  margin-top: 6px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.load-error {
  margin-bottom: 16px;
}

.actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.search-input {
  width: 240px;
}

.course-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
  min-height: 120px;
}

.course-card {
  cursor: pointer;
  position: relative;
  overflow: hidden;
}

.course-card:focus-visible {
  outline: 3px solid rgba(37, 99, 235, 0.42);
  outline-offset: 2px;
}

.course-card :deep(.el-card__body) {
  padding: 0;
}

.card-color {
  height: 6px;
}

.card-body {
  padding: 16px;
}

.card-name {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}

.card-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 13px;
  color: #606266;
  margin-bottom: 8px;
}

.card-desc {
  font-size: 13px;
  color: #909399;
  margin-bottom: 12px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-actions {
  display: flex;
  gap: 8px;
}

.pagination {
  margin-top: 24px;
  display: flex;
  justify-content: flex-end;
}

@media (max-width: 768px) {
  .page {
    padding: 16px;
  }

  .actions {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .search-input {
    width: 100%;
  }

  .course-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .pagination {
    justify-content: center;
  }
}

@media (max-width: 420px) {
  .actions {
    grid-template-columns: minmax(0, 1fr);
  }

  .actions :deep(.el-button) {
    width: 100%;
    margin-left: 0;
  }
}
</style>
