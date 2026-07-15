import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PageCanvas from './PageCanvas.vue'

const requestGet = vi.hoisted(() => vi.fn())
vi.mock('../../api', () => ({ default: { get: requestGet } }))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

const page = (key: string, url: string) => ({
  catalog_key: key,
  id: null,
  page_no: 1,
  is_synthetic: true,
  page_asset: { file_url: url, status: 'ready' },
  source_width: 100,
  source_height: 200,
  text_layer: [{ block_id: 'block-1', text: '可选择的正文', bbox: [10, 20, 90, 40] as [number, number, number, number], reading_order: 0, font_size: 10 }],
})

describe('PageCanvas', () => {
  beforeEach(() => {
    requestGet.mockReset()
  })

  it('revokes a late Blob from an obsolete material request instead of displaying it', async () => {
    const oldRequest = deferred<{ data: Blob }>()
    const newRequest = deferred<{ data: Blob }>()
    requestGet.mockReturnValueOnce(oldRequest.promise).mockReturnValueOnce(newRequest.promise)
    // The current request resolves first, so it receives the first object URL.
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValueOnce('blob:new').mockReturnValueOnce('blob:old')
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)

    const wrapper = mount(PageCanvas, {
      props: { pages: [page('old-page', '/materials/page-assets/1/file')] },
      global: { stubs: { 'el-image': true, 'el-icon': true } },
    })
    await flushPromises()
    await wrapper.setProps({ pages: [page('new-page', '/materials/page-assets/2/file')] })
    await flushPromises()

    newRequest.resolve({ data: new Blob(['new'], { type: 'image/png' }) })
    await flushPromises()
    oldRequest.resolve({ data: new Blob(['old'], { type: 'image/png' }) })
    await flushPromises()

    expect(revokeObjectURL).toHaveBeenCalledWith('blob:old')
    expect(wrapper.html()).toContain('blob:new')
    expect(wrapper.html()).not.toContain('blob:old')
    createObjectURL.mockRestore()
    revokeObjectURL.mockRestore()
  })

  it('emits selected text with page, material, and block ids', async () => {
    requestGet.mockResolvedValue({ data: new Blob(['page'], { type: 'image/png' }) })
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:page')
    const wrapper = mount(PageCanvas, {
      props: { pages: [page('page-7', '/materials/page-assets/7/file')], materialId: 12 },
      global: { stubs: { 'el-icon': true } },
    })
    await flushPromises()
    const block = wrapper.find('[data-block-id="block-1"]')
    vi.spyOn(window, 'getSelection').mockReturnValue({
      toString: () => '可选择的正文',
      anchorNode: block.element.firstChild,
      containsNode: () => true,
    } as unknown as Selection)

    await wrapper.find('.text-layer').trigger('mouseup')

    expect(wrapper.emitted('selection')?.[0]?.[0]).toEqual({
      text: '可选择的正文', pageNo: 1, blockIds: ['block-1'], materialId: 12,
    })
    vi.restoreAllMocks()
  })
})
