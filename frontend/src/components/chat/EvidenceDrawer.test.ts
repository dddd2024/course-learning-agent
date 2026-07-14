import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import EvidenceDrawer from './EvidenceDrawer.vue'

const routerPush = vi.hoisted(() => vi.fn())
vi.mock('vue-router', () => ({ useRouter: () => ({ push: routerPush }) }))

describe('EvidenceDrawer', () => {
  beforeEach(() => routerPush.mockReset())

  it('opens a cited chunk through its stable public material identity', async () => {
    const wrapper = mount(EvidenceDrawer, {
      props: {
        visible: true,
        loading: false,
        citation: {
          chunk_id: 42,
          material_name: 'network.pdf',
          material_public_id: '00000000-0000-4000-8000-000000000042',
          page_no: 3,
          quote_text: 'data link layer',
          confidence: 1,
        },
        message: {
          role: 'agent',
          content: 'answer',
          courseId: 7,
        } as any,
        chunk: null,
      },
      global: {
        stubs: {
          'el-drawer': { template: '<div><slot /></div>' },
          'el-button': {
            props: ['disabled'],
            emits: ['click'],
            template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
          },
          'el-tag': { template: '<span><slot /></span>' },
          'el-empty': true,
          FollowUpSuggestions: true,
        },
      },
    })

    await wrapper.get('button').trigger('click')

    expect(routerPush).toHaveBeenCalledWith({
      path: '/courses/7/learn',
      query: {
        material: '00000000-0000-4000-8000-000000000042',
        chunk_id: '42',
      },
    })
    expect(wrapper.emitted('update:visible')).toEqual([[false]])
  })
})
