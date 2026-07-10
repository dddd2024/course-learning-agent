<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getCourse } from '../../api/course'

const route = useRoute()
const router = useRouter()
const courseName = ref('')

const courseId = computed(() => {
  const m = route.path.match(/\/courses\/(\d+)/)
  return m ? Number(m[1]) : null
})

// Fetch course name when course ID changes
watch(courseId, async (id) => {
  if (id) {
    try {
      const { data } = await getCourse(id)
      courseName.value = data.name
    } catch {
      courseName.value = ''
    }
  } else {
    courseName.value = ''
  }
}, { immediate: true })

interface Crumb {
  label: string
  to?: string
}

const crumbs = computed<Crumb[]>(() => {
  const path = route.path
  const result: Crumb[] = [{ label: '首页', to: '/dashboard' }]

  if (path === '/dashboard') return result

  if (path.startsWith('/courses')) {
    result.push({ label: '课程', to: '/courses' })

    if (courseId.value) {
      const name = courseName.value || `课程 ${courseId.value}`
      result.push({ label: name, to: `/courses/${courseId.value}` })

      if (path.endsWith('/materials')) result.push({ label: '资料' })
      else if (path.endsWith('/chat')) result.push({ label: '问答' })
      else if (path.endsWith('/learn')) result.push({ label: '学习' })
      else if (path.endsWith('/outline')) result.push({ label: '知识点' })
    }
  } else if (path === '/todos') {
    result.push({ label: '待办' })
  } else if (path.startsWith('/plans')) {
    result.push({ label: '计划', to: '/plans' })
    if (path === '/plans/multi') result.push({ label: '多课程计划' })
  } else if (path === '/quizzes') {
    result.push({ label: '测验' })
  } else if (path === '/knowledge-graph') {
    result.push({ label: '知识图谱' })
  } else if (path === '/profile') {
    result.push({ label: '个人中心' })
  } else if (path === '/logs') {
    result.push({ label: '日志中心' })
  }

  return result
})

function navigate(to: string | undefined, isLast: boolean) {
  if (to && !isLast) router.push(to)
}
</script>

<template>
  <el-breadcrumb separator="/" class="app-breadcrumbs">
    <el-breadcrumb-item
      v-for="(crumb, i) in crumbs"
      :key="i"
      @click="navigate(crumb.to, i === crumbs.length - 1)"
    >
      <span :class="{ clickable: crumb.to && i < crumbs.length - 1 }">
        {{ crumb.label }}
      </span>
    </el-breadcrumb-item>
  </el-breadcrumb>
</template>

<style scoped>
.app-breadcrumbs {
  padding: 0 20px;
  height: 36px;
  line-height: 36px;
  background: #fff;
  border-bottom: 1px solid #f0f0f0;
}
.clickable {
  cursor: pointer;
  color: #409eff;
}
.clickable:hover {
  text-decoration: underline;
}
</style>
