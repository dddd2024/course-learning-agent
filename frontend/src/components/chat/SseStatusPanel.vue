<script setup lang="ts">
// Display-only SSE progress panel. The parent owns the step state and
// the expanded flag; this component only renders and emits toggles.
import {
  ArrowDown,
  ArrowUp,
  CircleCheck,
  CircleClose,
  Loading,
} from '@element-plus/icons-vue'
import type { StreamStep } from './types'

const props = defineProps<{
  steps: StreamStep[]
  error: string | null
  advice: string | null
  expanded: boolean
  runningStep?: StreamStep
}>()

const emit = defineEmits<{
  (e: 'toggle'): void
}>()

const hasError = () => props.error !== null

// Human-readable label for an SSE step name.
function stepLabel(step: string | undefined): string {
  switch (step) {
    case 'retrieve':
      return '检索资料'
    case 'generate':
      return '生成回答'
    case 'citation':
      return '整理引用'
    default:
      return step || '处理中'
  }
}
</script>

<template>
  <div
    v-if="props.steps.length > 0"
    class="stream-status"
    :class="{
      'status-error': hasError(),
      'status-collapsed': !props.expanded,
    }"
  >
    <div class="status-header" @click="emit('toggle')">
      <el-icon
        v-if="props.runningStep && !hasError()"
        class="is-loading"
      >
        <Loading />
      </el-icon>
      <el-icon v-else-if="hasError()" class="status-err-icon">
        <CircleClose />
      </el-icon>
      <el-icon v-else class="status-ok-icon">
        <CircleCheck />
      </el-icon>
      <span class="status-summary">
        <template v-if="hasError()">
          处理失败：{{ props.error }}
        </template>
        <template v-else-if="props.runningStep">
          {{ props.runningStep.message }}
        </template>
        <template v-else>
          已完成（{{ props.steps.length }} 个步骤）
        </template>
      </span>
      <el-icon class="status-toggle">
        <ArrowUp v-if="props.expanded" />
        <ArrowDown v-else />
      </el-icon>
    </div>
    <div v-if="props.expanded" class="status-body">
      <div
        v-for="s in props.steps"
        :key="s.step"
        class="status-step"
        :class="`step-${s.status}`"
      >
        <el-icon v-if="s.status === 'running'" class="is-loading">
          <Loading />
        </el-icon>
        <el-icon v-else-if="s.status === 'done'" class="step-done-icon">
          <CircleCheck />
        </el-icon>
        <el-icon v-else class="step-err-icon">
          <CircleClose />
        </el-icon>
        <span class="step-name">{{ stepLabel(s.step) }}</span>
        <span class="step-message">{{ s.message }}</span>
      </div>
      <el-alert
        v-if="hasError() && props.advice"
        :title="props.advice"
        type="warning"
        :closable="false"
        show-icon
        class="status-advice"
      />
    </div>
  </div>
</template>

<style scoped>
.stream-status {
  border-top: 1px solid #ebeef5;
  background: #fafbfc;
  flex-shrink: 0;
}

.stream-status.status-error {
  background: #fef0f0;
  border-top-color: #fbc4c4;
}

.status-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  cursor: pointer;
  user-select: none;
  font-size: 13px;
  color: #606266;
}

.status-header:hover {
  background: #f5f7fa;
}

.stream-status.status-error .status-header {
  color: #f56c6c;
}

.status-summary {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-err-icon {
  color: #f56c6c;
  flex-shrink: 0;
}

.status-ok-icon {
  color: #67c23a;
  flex-shrink: 0;
}

.status-toggle {
  color: #909399;
  flex-shrink: 0;
}

.status-body {
  padding: 4px 16px 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.status-step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  padding: 4px 0;
}

.step-name {
  font-weight: 600;
  color: #303133;
  flex-shrink: 0;
  min-width: 64px;
}

.step-message {
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.status-step.step-running .step-name {
  color: #409eff;
}

.status-step.step-done .step-name {
  color: #67c23a;
}

.step-done-icon {
  color: #67c23a;
  flex-shrink: 0;
}

.step-err-icon {
  color: #f56c6c;
  flex-shrink: 0;
}

.status-advice {
  margin-top: 4px;
}
</style>
