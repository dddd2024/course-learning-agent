<template>
  <section class="page-canvas" aria-label="原页阅读器">
    <div v-if="!pages.length" class="page-empty">暂无可用页图</div>
    <article v-for="page in pages" :id="`page-${page.page_no}`" :key="page.id" class="page-sheet">
      <div class="page-meta">第 {{ page.page_no }} 页</div>
      <el-image v-if="page.page_asset?.file_url && urls[page.id]" :src="urls[page.id]" :preview-src-list="[urls[page.id]]" fit="contain" loading="lazy" :alt="`资料第 ${page.page_no} 页原页图像`" class="page-image" />
      <div v-else class="page-unavailable">{{ page.page_asset?.status === 'failed' ? '页图渲染失败，请使用结构化文本查看。' : '页图加载中或尚未生成。' }}</div>
    </article>
  </section>
</template>

<script setup lang="ts">
import { reactive, watch } from 'vue'
import request from '../../api'
interface PageAsset { file_url?: string; status?: string }
interface ReaderPage { id: number; page_no: number; page_asset?: PageAsset | null }
const props = defineProps<{ pages: ReaderPage[] }>()
const urls = reactive<Record<number, string>>({})
async function loadAssets() {
  await Promise.allSettled(props.pages.map(async (page) => {
    if (!page.page_asset?.file_url || urls[page.id]) return
    // The API catalogue exposes an app-root URL.  Axios already has
    // ``/api/v1`` as its base URL, so remove that one prefix before issuing
    // the authenticated request instead of producing ``/api/v1/api/v1/...``.
    const fileUrl = page.page_asset.file_url.startsWith('/api/v1/')
      ? page.page_asset.file_url.slice('/api/v1'.length)
      : page.page_asset.file_url
    const { data } = await request.get(fileUrl, { responseType: 'blob' })
    urls[page.id] = URL.createObjectURL(data)
  }))
}
watch(() => props.pages, loadAssets, { immediate: true, deep: true })
</script>

<style scoped>
.page-canvas { max-width: 980px; margin: 0 auto; display: grid; gap: 24px; }
.page-sheet { background: #fff; border: 1px solid #e4e7ed; border-radius: 8px; padding: 12px; box-shadow: 0 1px 4px rgb(0 0 0 / 6%); }
.page-meta { color: #606266; font-size: 13px; margin: 0 0 8px; }
.page-image { display: block; width: 100%; min-height: 240px; background: #f5f7fa; }
.page-unavailable, .page-empty { padding: 48px 16px; text-align: center; color: #909399; background: #f5f7fa; }
</style>
