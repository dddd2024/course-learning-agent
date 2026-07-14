<template>
  <section class="page-canvas" aria-label="原页阅读器">
    <div v-if="!pages.length" class="page-empty">暂无可用页图</div>
    <article v-for="page in pages" :id="`page-${page.page_no}`" :key="page.id" class="page-sheet">
      <div class="page-meta">第 {{ page.page_no }} 页</div>

      <div v-if="states[page.id] === 'failed'" class="page-error">
        <el-icon><PictureRounded /></el-icon>
        <span>第 {{ page.page_no }} 页{{ errors[page.id] === 'decode' ? '图像损坏' : '加载失败' }}</span>
        <span class="page-error-hint">可重试本页，或暂时使用结构化文本查看。</span>
        <el-button size="small" type="primary" plain @click="retryPage(page)">重试本页</el-button>
      </div>

      <div v-else-if="!page.page_asset" class="page-unavailable">
        此页无关联资产，请尝试修复预览。
      </div>

      <el-image
        v-else-if="states[page.id] === 'ready' && urls[page.id]"
        :src="urls[page.id]"
        :preview-src-list="[urls[page.id]]"
        fit="contain"
        loading="lazy"
        :alt="`资料第 ${page.page_no} 页原页图像`"
        class="page-image"
        @error="handleImageError(page.id)"
      />

      <div v-else-if="page.page_asset?.status === 'failed'" class="page-error">
        <el-icon><PictureRounded /></el-icon>
        <span>第 {{ page.page_no }} 页渲染失败</span>
        <span class="page-error-hint">请修复文档预览或使用结构化文本。</span>
      </div>

      <div v-else class="page-unavailable">
        {{ states[page.id] === 'loading' ? '页图加载中。' : '页图尚未生成。' }}
      </div>
    </article>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, reactive, watch } from 'vue'
import { PictureRounded } from '@element-plus/icons-vue'
import request from '../../api'

interface PageAsset {
  file_url?: string
  status?: string
  sha256?: string | null
}

interface ReaderPage {
  id: number
  page_no: number
  page_asset?: PageAsset | null
}

type PageLoadState = 'idle' | 'loading' | 'ready' | 'failed'
type PageLoadError = 'network' | 'empty' | 'decode'

const props = defineProps<{ pages: ReaderPage[] }>()
const urls = reactive<Record<number, string>>({})
const states = reactive<Record<number, PageLoadState>>({})
const errors = reactive<Record<number, PageLoadError | undefined>>({})
const sourceKeys = reactive<Record<number, string>>({})
let retryNonce = 0

function sourceKey(page: ReaderPage): string {
  const asset = page.page_asset
  return `${asset?.file_url || ''}|${asset?.sha256 || ''}|${asset?.status || ''}`
}

function revokePageUrl(pageId: number) {
  const current = urls[pageId]
  if (current) {
    URL.revokeObjectURL(current)
    delete urls[pageId]
  }
}

function clearPage(pageId: number) {
  revokePageUrl(pageId)
  delete states[pageId]
  delete errors[pageId]
  delete sourceKeys[pageId]
}

function normalizedApiUrl(raw: string): string {
  return raw.startsWith('/api/v1/') ? raw.slice('/api/v1'.length) : raw
}

async function loadPage(page: ReaderPage, force = false) {
  const asset = page.page_asset
  const key = sourceKey(page)

  if (!asset?.file_url || asset.status !== 'ready') {
    revokePageUrl(page.id)
    sourceKeys[page.id] = key
    states[page.id] = 'idle'
    errors[page.id] = undefined
    return
  }

  if (!force && sourceKeys[page.id] === key && states[page.id] === 'ready' && urls[page.id]) {
    return
  }

  revokePageUrl(page.id)
  sourceKeys[page.id] = key
  states[page.id] = 'loading'
  errors[page.id] = undefined

  const fileUrl = normalizedApiUrl(asset.file_url)
  const separator = fileUrl.includes('?') ? '&' : '?'
  const requestUrl = force ? `${fileUrl}${separator}_retry=${Date.now()}-${retryNonce++}` : fileUrl

  try {
    const { data } = await request.get(requestUrl, { responseType: 'blob' })
    // A page can be removed or receive a new asset while the old request is
    // in flight. Ignore that stale response instead of leaking an Object URL
    // or overwriting the new page state.
    if (sourceKeys[page.id] !== key) return
    if (!(data instanceof Blob) || data.size === 0) {
      states[page.id] = 'failed'
      errors[page.id] = 'empty'
      return
    }
    urls[page.id] = URL.createObjectURL(data)
    states[page.id] = 'ready'
  } catch {
    if (sourceKeys[page.id] !== key) return
    states[page.id] = 'failed'
    errors[page.id] = 'network'
  }
}

async function retryPage(page: ReaderPage) {
  await loadPage(page, true)
}

function handleImageError(pageId: number) {
  revokePageUrl(pageId)
  states[pageId] = 'failed'
  errors[pageId] = 'decode'
}

async function syncPages() {
  const activeIds = new Set(props.pages.map((page) => page.id))
  for (const storedId of Object.keys(states).map(Number)) {
    if (!activeIds.has(storedId)) clearPage(storedId)
  }

  await Promise.allSettled(
    props.pages.map(async (page) => {
      const key = sourceKey(page)
      if (sourceKeys[page.id] && sourceKeys[page.id] !== key) {
        clearPage(page.id)
      }
      await loadPage(page)
    }),
  )
}

watch(() => props.pages, () => { void syncPages() }, { immediate: true, deep: true })

onBeforeUnmount(() => {
  for (const pageId of Object.keys(urls).map(Number)) revokePageUrl(pageId)
})
</script>

<style scoped>
.page-canvas { max-width: 980px; margin: 0 auto; display: grid; gap: 24px; }
.page-sheet { background: #fff; border: 1px solid #e4e7ed; border-radius: 8px; padding: 12px; box-shadow: 0 1px 4px rgb(0 0 0 / 6%); }
.page-meta { color: #606266; font-size: 13px; margin: 0 0 8px; }
.page-image { display: block; width: 100%; min-height: 240px; background: #f5f7fa; }
.page-unavailable, .page-empty { padding: 48px 16px; text-align: center; color: #909399; background: #f5f7fa; }
.page-error { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; padding: 40px 20px; color: #f56c6c; background: #fef0f0; border: 1px dashed #fbc4c4; border-radius: 6px; }
.page-error .el-icon { font-size: 28px; }
.page-error-hint { font-size: 12px; color: #909399; }
</style>
