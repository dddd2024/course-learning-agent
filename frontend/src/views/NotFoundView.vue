<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()

function goHome() {
  router.push('/dashboard')
}
</script>

<template>
  <div class="not-found">
    <h1>404</h1>
    <p class="desc">抱歉，您访问的页面不存在。</p>
    <el-button type="primary" @click="goHome">返回首页</el-button>
  </div>
</template>

<style scoped>
.not-found {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  text-align: center;
}

.not-found h1 {
  font-size: 72px;
  color: #409eff;
  margin-bottom: 16px;
}

.desc {
  color: #606266;
  margin-bottom: 24px;
}
</style>
