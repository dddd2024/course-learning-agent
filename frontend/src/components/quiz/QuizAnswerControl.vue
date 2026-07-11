<script setup lang="ts">
import type { QuizItem } from '../../api/quiz'

const props = defineProps<{
  item: Pick<QuizItem, 'id' | 'question_type' | 'options'>
  modelValue: string | string[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string | string[]]
}>()

function updateMultiple(value: string, checked: boolean) {
  const values = Array.isArray(props.modelValue) ? [...props.modelValue] : []
  const next = checked
    ? [...new Set([...values, value])]
    : values.filter((entry) => entry !== value)
  emit('update:modelValue', next)
}
</script>

<template>
  <div class="quiz-answer-control">
    <template v-if="item.question_type === 'choice' || item.question_type === 'true_false'">
      <label v-for="option in item.options" :key="option.value" class="answer-option">
        <input
          type="radio"
          :name="`quiz-question-${item.id}`"
          :value="option.value"
          :checked="modelValue === option.value"
          @change="emit('update:modelValue', option.value)"
        >
        {{ option.label }}. {{ option.text }}
      </label>
    </template>
    <template v-else-if="item.question_type === 'multiple_choice'">
      <label v-for="option in item.options" :key="option.value" class="answer-option">
        <input
          type="checkbox"
          :value="option.value"
          :checked="Array.isArray(modelValue) && modelValue.includes(option.value)"
          @change="updateMultiple(option.value, ($event.target as HTMLInputElement).checked)"
        >
        {{ option.label }}. {{ option.text }}
      </label>
    </template>
    <textarea
      v-else
      :value="typeof modelValue === 'string' ? modelValue : ''"
      rows="3"
      placeholder="请输入答案"
      @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
    />
  </div>
</template>

<style scoped>
.quiz-answer-control {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.answer-option {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  line-height: 1.5;
  cursor: pointer;
  overflow-wrap: anywhere;
}

textarea {
  width: 100%;
  box-sizing: border-box;
  resize: vertical;
  padding: 8px 10px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  font: inherit;
}
</style>
