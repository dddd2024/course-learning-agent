<template>
  <div class="page-text-panel" @mouseup="$emit('select')">
    <article v-for="page in pages" :id="`page-${page.page_no}`" :key="page.id" class="text-page">
      <div class="text-page-meta">第 {{ page.page_no }} 页</div>
      <div class="text-page-content">{{ mode === 'raw' ? page.raw_text : page.clean_text }}</div>
    </article>
  </div>
</template>

<script setup lang="ts">
defineProps<{ pages: Array<{ id: number; page_no: number; raw_text: string; clean_text: string }>; mode: 'raw' | 'clean' }>()
defineEmits<{ select: [] }>()
</script>

<style scoped>
.page-text-panel { display: grid; gap: 20px; }
.text-page { padding: 16px 20px; background: #fff; border: 1px solid #ebeef5; border-left: 4px solid #409eff; border-radius: 8px; }
.text-page-meta { margin-bottom: 10px; color: #909399; font-size: 12px; }
.text-page-content { white-space: pre-wrap; word-break: break-word; font-size: 14px; line-height: 1.8; color: #303133; }
</style>
