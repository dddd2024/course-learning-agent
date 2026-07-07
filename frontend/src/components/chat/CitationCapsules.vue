<script setup lang="ts">
// Display-only citation capsules. Renders the list of citations as
// clickable pills; the parent owns the open-citation action.
import type { Citation } from '../../api/chat'

const props = defineProps<{
  citations: Citation[]
}>()

const emit = defineEmits<{
  (e: 'open', citation: Citation): void
}>()

// Prefer the backend-assembled ``display_label``; fall back to
// client-side assembly for older data.
function capsuleLabel(cit: Citation): string {
  if (cit.display_label) return cit.display_label
  if (cit.page_no !== null && cit.page_no !== undefined) {
    return `${cit.material_name} · 第 ${cit.page_no} 页`
  }
  return cit.material_name || `片段 ${cit.chunk_id}`
}
</script>

<template>
  <div class="citation-capsules">
    <span
      v-for="(cit, ci) in props.citations"
      :key="`${cit.chunk_id}-${ci}`"
      class="citation-capsule"
      :title="'点击查看原文证据'"
      @click="emit('open', cit)"
    >
      <span class="capsule-index">{{ ci + 1 }}</span>
      <span class="capsule-label">{{ capsuleLabel(cit) }}</span>
    </span>
  </div>
</template>

<style scoped>
.citation-capsules {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}

.citation-capsule {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border-radius: 999px;
  background: #f4f6f9;
  border: 1px solid #e4e7ed;
  font-size: 12px;
  color: #606266;
  cursor: pointer;
  transition: all 0.2s;
  max-width: 280px;
}

.citation-capsule:hover {
  background: #ecf5ff;
  border-color: #c6e2ff;
  color: #409eff;
}

.capsule-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #dcdfe6;
  color: #606266;
  font-size: 10px;
  font-weight: 600;
  flex-shrink: 0;
}

.citation-capsule:hover .capsule-index {
  background: #409eff;
  color: #fff;
}

.capsule-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
