<template>
  <section class="page-canvas" aria-label="原页阅读器">
    <div v-if="!pages.length" class="page-empty">暂无可用页图</div>
    <article v-for="page in pages" :id="`page-${page.page_no}`" :key="page.catalog_key" class="page-sheet">
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
      <el-image
        v-else-if="page.page_asset.file_url && page.page_asset.status === 'ready' && urls[page.catalog_key]"
        :src="urls[page.catalog_key]" :preview-src-list="[urls[page.catalog_key]]" fit="contain" loading="lazy"
        :alt="`资料第 ${page.page_no} 页原页图像`" class="page-image" @error="handleImageError(page.catalog_key)"
      />
      <div v-else-if="page.page_asset.status === 'failed'" class="page-error">第 {{ page.page_no }} 页渲染失败</div>
      <div v-else class="page-unavailable">页图加载中或尚未生成。</div>
    </article>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, reactive, watch } from 'vue'
import { PictureRounded } from '@element-plus/icons-vue'
import request from '../../api'

interface PageAsset { file_url?: string; status?: string }
interface ReaderPage { catalog_key: string; id: number | null; page_no: number; is_synthetic: boolean; page_asset?: PageAsset | null }
const props = defineProps<{ pages: ReaderPage[] }>()
const urls = reactive<Record<string, string>>({})
const loadErrors = reactive<Set<string>>(new Set())
const imageErrors = reactive<Set<string>>(new Set())

function releaseUrl(key: string) {
  if (urls[key]) { URL.revokeObjectURL(urls[key]); delete urls[key] }
}
function releaseAllUrls() { Object.keys(urls).forEach(releaseUrl) }
function handleImageError(key: string) { imageErrors.add(key); releaseUrl(key) }

async function loadPage(page: ReaderPage) {
  const key = page.catalog_key
  if (!page.page_asset?.file_url || urls[key]) return
  loadErrors.delete(key); imageErrors.delete(key)
  const fileUrl = page.page_asset.file_url.startsWith('/api/v1/') ? page.page_asset.file_url.slice('/api/v1'.length) : page.page_asset.file_url
  try {
    const { data } = await request.get(fileUrl, { responseType: 'blob' })
    if (!data || data.size <= 0 || !String(data.type || '').startsWith('image/')) { loadErrors.add(key); return }
    urls[key] = URL.createObjectURL(data)
  } catch { loadErrors.add(key) }
}
async function loadAssets() { await Promise.allSettled(props.pages.map(loadPage)) }
async function retryPage(page: ReaderPage) {
  releaseUrl(page.catalog_key); loadErrors.delete(page.catalog_key); imageErrors.delete(page.catalog_key); await loadPage(page)
}
watch(() => props.pages, async () => { releaseAllUrls(); loadErrors.clear(); imageErrors.clear(); await loadAssets() }, { immediate: true, deep: true })
onBeforeUnmount(releaseAllUrls)
</script>

<style scoped>
.page-canvas { max-width: 980px; margin: 0 auto; display: grid; gap: 24px; }
.page-sheet { background: #fff; border: 1px solid #e4e7ed; border-radius: 8px; padding: 12px; box-shadow: 0 1px 4px rgb(0 0 0 / 6%); }
.page-meta { color: #606266; font-size: 13px; margin: 0 0 8px; }.page-image { display: block; width: 100%; min-height: 240px; background: #f5f7fa; }
.page-unavailable, .page-empty { padding: 48px 16px; text-align: center; color: #909399; background: #f5f7fa; }
.page-error { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; padding: 40px 20px; color: #f56c6c; background: #fef0f0; border: 1px dashed #fbc4c4; border-radius: 6px; }
</style>
