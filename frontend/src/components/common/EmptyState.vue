<script setup lang="ts">
import type { Component } from 'vue'
import { Box } from '@element-plus/icons-vue'

defineProps<{
  icon?: Component
  title: string
  description?: string
  actionText?: string
}>()

defineEmits<{
  action: []
}>()
</script>

<template>
  <div class="empty-state">
    <el-icon v-if="icon" :size="56" class="empty-icon">
      <component :is="icon" />
    </el-icon>
    <el-icon v-else :size="56" class="empty-icon">
      <Box />
    </el-icon>
    <h3 class="empty-title">{{ title }}</h3>
    <p v-if="description" class="empty-desc">{{ description }}</p>
    <el-button v-if="actionText" type="primary" @click="$emit('action')">
      {{ actionText }}
    </el-button>
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  text-align: center;
}
.empty-icon {
  color: #c0c4cc;
  margin-bottom: 16px;
}
.empty-title {
  font-size: 16px;
  font-weight: 500;
  color: #606266;
  margin: 0 0 8px;
}
.empty-desc {
  font-size: 14px;
  color: #909399;
  margin: 0 0 20px;
  max-width: 400px;
  line-height: 1.5;
}
</style>
