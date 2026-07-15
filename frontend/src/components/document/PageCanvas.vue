<template>
  <section class="page-canvas" aria-label="原页阅读器">
    <div v-if="!pages.length" class="page-empty">暂无可用页图</div>
    <article v-for="page in pages" :id="`page-${page.page_no}`" :key="page.catalog_key" class="page-sheet" :data-page-no="page.page_no" :data-catalog-key="page.catalog_key">
      <div class="page-meta">第 {{ page.page_no }} 页</div>
      <div v-if="imageErrors.has(page.catalog_key)" class="page-error">
        <el-icon><PictureRounded /></el-icon><span>第 {{ page.page_no }} 页图像损坏</span>
        <button type="button" @click="retryPage(page)">重新加载此页</button>
      </div>
      <div v-else-if="loadErrors.has(page.catalog_key)" class="page-error">
        <el-icon><PictureRounded /></el-icon><span>第 {{ page.page_no }} 页加载失败</span>
        <button type="button" @click="retryPage(page)">重新加载此页</button>
      </div>
      <div v-else-if="!page.page_asset" class="page-unavailable">此页无关联资产，请尝试修复预览。</div>
      <div
        v-else-if="page.page_asset.file_url && page.page_asset.status === 'ready' && urls[page.catalog_key]"
        class="page-stage"
      >
        <img
          :src="urls[page.catalog_key]"
          loading="lazy"
          :alt="`资料第 ${page.page_no} 页原页图像`"
          class="page-image"
          @error="handleImageError(page.catalog_key)"
        />
        <div
          v-if="page.text_layer?.length && page.source_width && page.source_height"
          class="text-layer"
          :aria-label="`第 ${page.page_no} 页可选文本`"
          @mouseup="emitSelection(page)"
        >
          <span
            v-for="block in page.text_layer"
            :key="block.block_id"
            :data-block-id="block.block_id"
            :style="overlayStyle(block, page)"
          >{{ block.text }}</span>
        </div>
        <div v-else class="text-layer-unavailable">该页暂无可选文本</div>
      </div>
      <div v-else-if="page.page_asset.status === 'failed'" class="page-error">第 {{ page.page_no }} 页渲染失败</div>
      <div v-else class="page-unavailable">页图加载中或尚未生成。</div>
    </article>
  </section>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, reactive, watch } from 'vue'
import { PictureRounded } from '@element-plus/icons-vue'
import request from '../../api'
import { normalizeApiAssetUrl } from '../../utils/assetUrl'

interface PageAsset { file_url?: string; status?: string }
interface TextBlock { block_id: string; text: string; bbox: [number, number, number, number]; reading_order: number; font_size?: number | null }
interface ReaderPage { catalog_key: string; id: number | null; page_no: number; is_synthetic: boolean; source_width?: number | null; source_height?: number | null; text_layer?: TextBlock[]; page_asset?: PageAsset | null }
const props = defineProps<{ pages: ReaderPage[]; materialId?: number | null }>()
const emit = defineEmits<{ selection: [payload: { text: string; pageNo: number; blockIds: string[]; materialId: number }] }>()
const urls = reactive<Record<string, string>>({})
const loadErrors = reactive<Set<string>>(new Set())
const imageErrors = reactive<Set<string>>(new Set())
const controllers = new Map<string, AbortController>()
let generation = 0
let pageObserver: IntersectionObserver | null = null

function releaseUrl(key: string) {
  if (urls[key]) { URL.revokeObjectURL(urls[key]); delete urls[key] }
}
function releaseAllUrls() { Object.keys(urls).forEach(releaseUrl) }
function handleImageError(key: string) { imageErrors.add(key); releaseUrl(key) }

function overlayStyle(block: TextBlock, page: ReaderPage) {
  const width = page.source_width || 1
  const height = page.source_height || 1
  const [x0, y0, x1, y1] = block.bbox
  return {
    left: `${(x0 / width) * 100}%`,
    top: `${(y0 / height) * 100}%`,
    width: `${Math.max(0, (x1 - x0) / width) * 100}%`,
    height: `${Math.max(0, (y1 - y0) / height) * 100}%`,
    fontSize: `${Math.max(0.5, ((block.font_size || 10) / width) * 100)}cqw`,
  }
}

function emitSelection(page: ReaderPage) {
  const selection = window.getSelection()
  const text = selection?.toString().trim().slice(0, 2000) || ''
  if (!text || !props.materialId || !selection) return
  const layer = (selection.anchorNode instanceof Element ? selection.anchorNode : selection.anchorNode?.parentElement)?.closest('.text-layer')
  if (!layer) return
  const blockIds = Array.from(layer.querySelectorAll<HTMLElement>('[data-block-id]'))
    .filter((element) => selection.containsNode(element, true))
    .map((element) => element.dataset.blockId || '')
    .filter(Boolean)
  emit('selection', { text, pageNo: page.page_no, blockIds, materialId: props.materialId })
}

function signature(page: ReaderPage) {
  return `${page.catalog_key}|${page.page_asset?.file_url || ''}|${page.page_asset?.status || ''}`
}
function stillCurrent(page: ReaderPage, token: number) {
  return token === generation && props.pages.some((current) => signature(current) === signature(page))
}
function abortInFlight() {
  controllers.forEach((controller) => controller.abort())
  controllers.clear()
}
function disconnectPageObserver() {
  pageObserver?.disconnect()
  pageObserver = null
}

async function loadPage(page: ReaderPage, token = generation) {
  const key = page.catalog_key
  if (!page.page_asset?.file_url || urls[key]) return
  loadErrors.delete(key); imageErrors.delete(key)
  const fileUrl = normalizeApiAssetUrl(page.page_asset.file_url)
  const controller = new AbortController()
  controllers.get(key)?.abort()
  controllers.set(key, controller)
  try {
    const { data } = await request.get(fileUrl, { responseType: 'blob', signal: controller.signal })
    if (!data || data.size <= 0 || !String(data.type || '').startsWith('image/')) {
      if (stillCurrent(page, token)) loadErrors.add(key)
      return
    }
    const objectUrl = URL.createObjectURL(data)
    if (!stillCurrent(page, token)) { URL.revokeObjectURL(objectUrl); return }
    releaseUrl(key)
    urls[key] = objectUrl
  } catch (error) {
    if (stillCurrent(page, token) && (error as { name?: string })?.name !== 'CanceledError' && (error as { name?: string })?.name !== 'AbortError') loadErrors.add(key)
  } finally {
    if (controllers.get(key) === controller) controllers.delete(key)
  }
}
async function retryPage(page: ReaderPage) {
  releaseUrl(page.catalog_key); loadErrors.delete(page.catalog_key); imageErrors.delete(page.catalog_key); await loadPage(page)
}
watch(
  () => props.pages.map(signature).join('\u0001'),
  async () => {
    generation += 1
    const token = generation
    disconnectPageObserver(); abortInFlight(); releaseAllUrls(); loadErrors.clear(); imageErrors.clear()
    await nextTick()

    // Load the first spread immediately, then fetch later pages only as the
    // learner scrolls near them. Large slide decks otherwise opened hundreds
    // of authenticated Blob requests and retained every page in memory.
    props.pages.slice(0, 2).forEach((page) => { void loadPage(page, token) })
    const deferredPages = props.pages.slice(2)
    if (deferredPages.length === 0) return
    if (typeof IntersectionObserver === 'undefined') return

    const root = document.querySelector('.doc-reader')
    pageObserver = new IntersectionObserver((entries, observer) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return
        observer.unobserve(entry.target)
        const key = (entry.target as HTMLElement).dataset.catalogKey
        const page = props.pages.find((candidate) => candidate.catalog_key === key)
        if (page) void loadPage(page, token)
      })
    }, { root, rootMargin: '720px 0px' })
    const deferredKeys = new Set(deferredPages.map((page) => page.catalog_key))
    document.querySelectorAll<HTMLElement>('.page-sheet[data-catalog-key]').forEach((element) => {
      if (deferredKeys.has(element.dataset.catalogKey || '')) pageObserver?.observe(element)
    })
  },
  { immediate: true },
)
onBeforeUnmount(() => { generation += 1; disconnectPageObserver(); abortInFlight(); releaseAllUrls() })
</script>

<style scoped>
.page-canvas { max-width: 980px; margin: 0 auto; display: grid; gap: 24px; }
.page-sheet { background: #fff; border: 1px solid #e4e7ed; border-radius: 8px; padding: 12px; box-shadow: 0 1px 4px rgb(0 0 0 / 6%); }
.page-meta { color: #606266; font-size: 13px; margin: 0 0 8px; }
.page-stage { position: relative; width: 100%; container-type: inline-size; }
.page-image { display: block; width: 100%; height: auto; min-height: 240px; background: #f5f7fa; }
.text-layer { position: absolute; inset: 0; overflow: hidden; user-select: text; }
.text-layer span { position: absolute; color: transparent; white-space: pre-wrap; line-height: 1; transform-origin: top left; cursor: text; }
.text-layer span::selection { color: transparent; background: rgb(64 158 255 / 35%); }
.text-layer-unavailable { position: absolute; right: 8px; bottom: 8px; padding: 3px 7px; border-radius: 4px; color: #606266; background: rgb(255 255 255 / 82%); font-size: 12px; pointer-events: none; }
.page-unavailable, .page-empty { padding: 48px 16px; text-align: center; color: #909399; background: #f5f7fa; }
.page-error { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; padding: 40px 20px; color: #f56c6c; background: #fef0f0; border: 1px dashed #fbc4c4; border-radius: 6px; }
</style>
