<template>
  <div class="page-text-panel">
    <article v-for="page in pages" :id="`page-${page.page_no}`" :key="page.catalog_key" class="text-page" :data-page-no="page.page_no" @mouseup="emitSelection(page.page_no)">
      <div class="text-page-meta">第 {{ page.page_no }} 页</div>
      <div class="text-page-content">{{ mode === 'raw' ? page.raw_text : page.clean_text }}</div>
    </article>
  </div>
</template>

<script setup lang="ts">
const props = defineProps<{ pages: Array<{ catalog_key: string; id: number | null; page_no: number; raw_text: string; clean_text: string }>; mode: 'raw' | 'clean'; materialId?: number | null }>()
const emit = defineEmits<{ select: [payload: { text: string; pageNo: number; blockIds: string[]; materialId: number }] }>()
function emitSelection(pageNo: number) {
  const text = window.getSelection()?.toString().trim().slice(0, 2000) || ''
  if (text && props.materialId) emit('select', { text, pageNo, blockIds: [], materialId: props.materialId })
}
</script>

<style scoped>
.page-text-panel { display: grid; gap: 20px; }
.text-page { padding: 16px 20px; background: #fff; border: 1px solid #ebeef5; border-left: 4px solid #409eff; border-radius: 8px; }
.text-page-meta { margin-bottom: 10px; color: #909399; font-size: 12px; }
.text-page-content { white-space: pre-wrap; word-break: break-word; font-size: 14px; line-height: 1.8; color: #303133; }
</style>
