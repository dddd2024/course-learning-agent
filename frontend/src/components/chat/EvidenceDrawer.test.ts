import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import EvidenceDrawer from './EvidenceDrawer.vue'

const routerPush = vi.hoisted(() => vi.fn())
const resolveMaterialPublicId = vi.hoisted(() => vi.fn())
vi.mock('vue-router', () => ({ useRouter: () => ({ push: routerPush }) }))
vi.mock('./materialRouteResolver', () => ({ resolveMaterialPublicId }))

const globalStubs = {
  'el-drawer': { template: '<div><slot /></div>' },
  'el-button': {
    emits: ['click'],
    template: '<button @click="$emit(\'click\')"><slot /></button>',
  },
  'el-tag': { template: '<span><slot /></span>' },
  'el-empty': true,
  FollowUpSuggestions: true,
}

describe('EvidenceDrawer', () => {
  beforeEach(() => {
    routerPush.mockReset()
    resolveMaterialPublicId.mockReset()
  })

  it('opens a cited chunk through its stable public material identity', async () => {
    resolveMaterialPublicId.mockResolvedValue('00000000-0000-4000-8000-000000000042')
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
      global: { stubs: globalStubs },
    })

    await wrapper.get('button').trigger('click')
    await Promise.resolve()

    expect(resolveMaterialPublicId).toHaveBeenCalledWith(
      7,
      42,
      '00000000-0000-4000-8000-000000000042',
    )
    expect(routerPush).toHaveBeenCalledWith({
      path: '/courses/7/learn',
      query: {
        material: '00000000-0000-4000-8000-000000000042',
        chunk_id: '42',
      },
    })
    expect(wrapper.emitted('update:visible')).toEqual([[false]])
  })

  it('resolves an uncited retrieval chunk before opening the learning route', async () => {
    resolveMaterialPublicId.mockResolvedValue('00000000-0000-4000-8000-000000000099')
    const wrapper = mount(EvidenceDrawer, {
      props: {
        visible: true,
        loading: false,
        citation: null,
        message: {
          role: 'agent',
          content: 'answer',
          courseId: 7,
          retrievedChunks: [{
            chunk_id: 99,
            score: 0.8,
            title: 'uncited chunk',
            page_no: 4,
            snippet: 'text',
            is_cited: false,
          }],
        } as any,
        chunk: null,
      },
      global: { stubs: globalStubs },
    })

    await wrapper.get('button').trigger('click')
    await Promise.resolve()

    expect(resolveMaterialPublicId).toHaveBeenCalledWith(7, 99, undefined)
    expect(routerPush).toHaveBeenCalledWith({
      path: '/courses/7/learn',
      query: {
        material: '00000000-0000-4000-8000-000000000099',
        chunk_id: '99',
      },
    })
  })
})
