<script setup lang="ts">
// Display-only follow-up question chips. Used both inline under an
// agent message and inside the evidence drawer.
const props = defineProps<{
  questions: string[]
}>()

const emit = defineEmits<{
  (e: 'select', question: string): void
}>()
</script>

<template>
  <div class="follow-ups">
    <div class="follow-ups-title">追问建议：</div>
    <div class="follow-up-chips">
      <el-tag
        v-for="(q, qi) in props.questions"
        :key="qi"
        class="follow-up-chip"
        effect="plain"
        @click="emit('select', q)"
      >
        {{ q }}
      </el-tag>
    </div>
  </div>
</template>

<style scoped>
.follow-ups {
  margin-top: 10px;
}

.follow-ups-title {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
}

.follow-up-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.follow-up-chip {
  cursor: pointer;
  transition: all 0.2s;
}

.follow-up-chip:hover {
  color: #409eff;
  border-color: #409eff;
  cursor: pointer;
}
</style>
