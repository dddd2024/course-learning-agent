import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import QuizAnswerControl from './QuizAnswerControl.vue'

const options = [
  { label: 'A', text: '页表', value: 'A' },
  { label: 'B', text: '快表', value: 'B' },
  { label: 'C', text: '缓存', value: 'C' },
]

describe('QuizAnswerControl', () => {
  it('submits the second single-choice option value, not its display text', async () => {
    const wrapper = mount(QuizAnswerControl, {
      props: { item: { id: 1, question_type: 'choice', options }, modelValue: '' },
    })

    await wrapper.findAll('input[type="radio"]')[1].setValue()
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['B'])
  })

  it('keeps multiple-choice answers as an array of option values', async () => {
    const wrapper = mount(QuizAnswerControl, {
      props: { item: { id: 2, question_type: 'multiple_choice', options }, modelValue: [] },
    })

    await wrapper.findAll('input[type="checkbox"]')[0].setValue(true)
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([['A']])
  })
})
