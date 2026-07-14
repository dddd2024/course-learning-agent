import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PageCanvas from '../../src/components/document/PageCanvas.vue'

const { getMock } = vi.hoisted(() => ({ getMock: vi.fn() }))
vi.mock('../../src/api', () => ({ default: { get: getMock } }))

const page = (fileUrl = '/api/v1/materials/page-assets/1/file', sha = 'sha-1') => ({
  id: 1,
  page_no: 1,
  page_asset: { file_url: fileUrl, status: 'ready', sha256: sha },
})

describe('PageCanvas', () => {
  const createObjectURL = vi.fn(() => 'blob:page-1')
  const revokeObjectURL = vi.fn()

  beforeEach(() => {
    getMock.mockReset()
    createObjectURL.mockClear()
    revokeObjectURL.mockClear()
    Object.defineProperty(URL, 'createObjectURL', { value: createObjectURL, configurable: true })
    Object.defineProperty(URL, 'revokeObjectURL', { value: revokeObjectURL, configurable: true })
  })

  it('retries a failed page without blocking the canvas', async () => {
    getMock
      .mockRejectedValueOnce(new Error('404'))
      .mockResolvedValueOnce({ data: new Blob(['png'], { type: 'image/png' }) })

    const wrapper = mount(PageCanvas, { props: { pages: [page()] } })
    await flushPromises()

    expect(wrapper.text()).toContain('第 1 页加载失败')
    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(getMock).toHaveBeenCalledTimes(2)
    expect(getMock.mock.calls[1][0]).toContain('_retry=')
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    expect(wrapper.find('img[alt*="原页图像"]').exists()).toBe(true)
  })

  it('reloads and revokes when the same page id receives a new source', async () => {
    getMock.mockResolvedValue({ data: new Blob(['png'], { type: 'image/png' }) })
    const wrapper = mount(PageCanvas, { props: { pages: [page()] } })
    await flushPromises()

    await wrapper.setProps({ pages: [page('/api/v1/materials/page-assets/2/file', 'sha-2')] })
    await flushPromises()

    expect(getMock).toHaveBeenCalledTimes(2)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:page-1')
  })

  it('revokes object URLs when pages disappear and on unmount', async () => {
    getMock.mockResolvedValue({ data: new Blob(['png'], { type: 'image/png' }) })
    const wrapper = mount(PageCanvas, { props: { pages: [page()] } })
    await flushPromises()

    await wrapper.setProps({ pages: [] })
    await flushPromises()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:page-1')

    await wrapper.setProps({ pages: [page()] })
    await flushPromises()
    wrapper.unmount()
    expect(revokeObjectURL).toHaveBeenCalledTimes(2)
  })

  it('keeps other pages visible when one page fails', async () => {
    getMock
      .mockResolvedValueOnce({ data: new Blob(['png'], { type: 'image/png' }) })
      .mockRejectedValueOnce(new Error('network'))

    const wrapper = mount(PageCanvas, {
      props: {
        pages: [
          page(),
          { ...page('/api/v1/materials/page-assets/2/file', 'sha-2'), id: 2, page_no: 2 },
        ],
      },
    })
    await flushPromises()

    expect(wrapper.findAll('article.page-sheet')).toHaveLength(2)
    expect(wrapper.text()).toContain('第 2 页加载失败')
    expect(wrapper.find('img[alt*="第 1 页"]').exists()).toBe(true)
  })
})
