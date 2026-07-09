# 知识点提纲来源片段展示改进 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 移除知识点卡片和复习提纲中逐个列出的来源片段标签，替换为简洁的片段数量摘要 + 可展开的查看弹窗。

**Architecture:** 前端纯 UI 改造，不涉及后端 API 变更。将 `OutlineView.vue` 中的 `kp-foot` 区域从"列出所有 chunk ID 标签"改为"显示数量摘要 + 查看按钮"，点击按钮打开一个弹窗以分页列表形式展示所有来源片段。复习提纲中的逗号分隔 chunk 列表也替换为数量摘要。

**Tech Stack:** Vue 3 + TypeScript + Element Plus

---

### Task 1: 移除知识点卡片中的来源片段标签列表，改为简洁摘要

**Files:**
- Modify: `frontend/src/views/OutlineView.vue:297-315`

- [ ] **Step 1: 替换 kp-foot 区域**

将以下代码：

```vue
<div class="kp-foot">
  <span class="kp-source-label">来源片段：</span>
  <template
    v-if="kp.source_chunk_ids && kp.source_chunk_ids.length > 0"
  >
    <el-tag
      v-for="cid in kp.source_chunk_ids"
      :key="cid"
      size="small"
      type="info"
      effect="plain"
      class="kp-source-tag"
      @click="openChunkDialog(cid)"
    >
      #{{ cid }}
    </el-tag>
  </template>
  <span v-else class="kp-source-empty">无</span>
</div>
```

替换为：

```vue
<div class="kp-foot">
  <span class="kp-source-label">来源片段：</span>
  <template
    v-if="kp.source_chunk_ids && kp.source_chunk_ids.length > 0"
  >
    <span class="kp-source-count">
      共 {{ kp.source_chunk_ids.length }} 个片段
    </span>
    <el-button
      link
      type="primary"
      size="small"
      @click="openSourceListDialog(kp)"
    >
      查看来源
    </el-button>
  </template>
  <span v-else class="kp-source-empty">无</span>
</div>
```

- [ ] **Step 2: 验证前端构建**

Run: `cd frontend && npm run build`
Expected: 构建成功（可能有未使用变量警告，后续 Task 会清理）

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/OutlineView.vue
git commit -m "refactor(outline): replace source chunk tag list with summary count"
```

---

### Task 2: 移除复习提纲中的来源片段列表

**Files:**
- Modify: `frontend/src/views/OutlineView.vue:365-377`

- [ ] **Step 1: 替换复习提纲中的 chunk 列表**

将以下代码：

```vue
<li v-if="kp.source_chunk_ids && kp.source_chunk_ids.length > 0">
  <strong>来源片段：</strong>
  <span>
    <template
      v-for="(cid, i) in kp.source_chunk_ids"
      :key="cid"
    >
      #{{ cid }}<span
        v-if="i < kp.source_chunk_ids.length - 1"
      >, </span>
    </template>
  </span>
</li>
```

替换为：

```vue
<li v-if="kp.source_chunk_ids && kp.source_chunk_ids.length > 0">
  <strong>来源片段：</strong>
  <span>共 {{ kp.source_chunk_ids.length }} 个片段</span>
</li>
```

- [ ] **Step 2: 验证前端构建**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/OutlineView.vue
git commit -m "refactor(outline): simplify source chunks in review outline to count"
```

---

### Task 3: 添加来源片段列表弹窗

**Files:**
- Modify: `frontend/src/views/OutlineView.vue`

- [ ] **Step 1: 添加弹窗状态变量**

在 `<script setup>` 中的 `currentChunkMaterialName` ref 之后添加：

```ts
const sourceListDialogVisible = ref(false)
const sourceListLoading = ref(false)
const currentSourceKp = ref<KnowledgePoint | null>(null)
const sourceListChunks = ref<ChunkWithSource[]>([])
```

- [ ] **Step 2: 添加 openSourceListDialog 函数**

在 `openChunkDialog` 函数之后添加：

```ts
async function openSourceListDialog(kp: KnowledgePoint) {
  currentSourceKp.value = kp
  sourceListDialogVisible.value = true
  sourceListLoading.value = true
  sourceListChunks.value = []
  try {
    const all = await fetchAllChunks()
    const idSet = new Set(kp.source_chunk_ids)
    sourceListChunks.value = all.filter((c) => idSet.has(c.chunk.id))
  } catch {
    // 静默失败
  } finally {
    sourceListLoading.value = false
  }
}
```

- [ ] **Step 3: 添加弹窗模板**

在现有 `el-dialog`（chunkDialogVisible）之后添加新的弹窗：

```vue
<el-dialog
  v-model="sourceListDialogVisible"
  :title="
    currentSourceKp
      ? `来源片段 — ${currentSourceKp.title}（共 ${currentSourceKp.source_chunk_ids?.length || 0} 个）`
      : '来源片段'
  "
  width="720px"
>
  <div v-loading="sourceListLoading" class="source-list-body">
    <template v-if="sourceListChunks.length > 0">
      <div
        v-for="item in sourceListChunks"
        :key="item.chunk.id"
        class="source-list-item"
        @click="openChunkDialog(item.chunk.id)"
      >
        <div class="source-list-item-head">
          <span class="source-list-item-id">#{{ item.chunk.id }}</span>
          <span class="source-list-item-material">{{ item.materialName }}</span>
          <span v-if="item.chunk.page_no" class="source-list-item-page">
            第 {{ item.chunk.page_no }} 页
          </span>
        </div>
        <div class="source-list-item-text">
          {{ item.chunk.text?.substring(0, 120) }}{{ item.chunk.text && item.chunk.text.length > 120 ? '…' : '' }}
        </div>
      </div>
    </template>
    <el-empty
      v-else-if="!sourceListLoading"
      description="未找到来源片段详情"
      :image-size="80"
    />
  </div>
</el-dialog>
```

- [ ] **Step 4: 添加弹窗样式**

在 `</style>` 之前添加：

```css
.source-list-body {
  max-height: 500px;
  overflow-y: auto;
}

.source-list-item {
  padding: 10px 12px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: border-color 0.2s;
}

.source-list-item:hover {
  border-color: #409eff;
  background: #f0f7ff;
}

.source-list-item-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.source-list-item-id {
  font-size: 13px;
  font-weight: 600;
  color: #409eff;
}

.source-list-item-material {
  font-size: 12px;
  color: #909399;
}

.source-list-item-page {
  font-size: 12px;
  color: #c0c4cc;
}

.source-list-item-text {
  font-size: 13px;
  color: #606266;
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.kp-source-count {
  font-size: 13px;
  color: #606266;
}
```

- [ ] **Step 5: 验证前端构建**

Run: `cd frontend && npm run build`
Expected: 构建成功，无错误

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/OutlineView.vue
git commit -m "feat(outline): add source chunk list dialog with paginated view"
```

---

### Task 4: 浏览器验证

- [ ] **Step 1: 启动前端 dev server（如未运行）**

Run: `cd frontend && npm run dev`

- [ ] **Step 2: 打开知识点提纲页面，验证卡片不再列出所有标签**

- [ ] **Step 3: 点击"查看来源"按钮，验证弹窗正确显示片段列表**

- [ ] **Step 4: 验证复习提纲不再列出逗号分隔的 chunk ID**
