# 审计问题整改 Implementation Plan

> **For agentic workers:** 本计划覆盖 .docx《课程学习助手_两次审计问题整改计划》中的 T01–T09 全部任务，分 4 个阶段执行。每个任务均有明确的文件路径、代码片段、验收命令与提交点。后端改动一律 TDD（先写失败测试 → 实现 → 验证通过），前端改动以 `npm run build` + HTTP 端点验证为准。

**Goal:** 把两次审计提出的 9 个问题（T01–T09）按 P0→P3 顺序整改到可演示、可审计、可生产配置的状态，分 4 个提交推送到 `origin/main`。

**Architecture:**
- 后端 FastAPI + SQLAlchemy + pytest（每个新端点/守卫先写失败测试）
- 前端 Vue 3 + Element Plus + Vite（每个改动以 `npm run build` 通过为准）
- 验收脚本 `scripts/verify_phase2_engineering.ps1` 自身需要修复
- 每个阶段一个 conventional commit；阶段 0 是 hotfix

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy / pytest / Vue 3 / Element Plus / Vite / GitHub Actions

---

## File Structure（按阶段列出会改动/创建的文件）

### Phase 0 (hotfix)
- Modify: `scripts/verify_phase2_engineering.ps1` — 修复 Select-String 主观指标残留检查
- Modify: `frontend/src/views/MaterialsView.vue` — 放开 ready/failed 重新解析入口
- (不改 CI yaml，仅触发 workflow_dispatch)

### Phase 1 (demo loop)
- Create: `backend/app/schemas/message.py` — 消息历史响应 schema
- Modify: `backend/app/api/v1/endpoints/conversations.py` — 新增 `GET /conversations/{id}/messages`
- Modify: `backend/app/agents/llm.py` — `call_llm` 返回 provider/fallback 标记
- Modify: `backend/app/services/chat_service.py` — 透传 provider/fallback；无 ready chunks 时短路
- Modify: `backend/app/schemas/chat.py` — `ChatResponse` 增加 `provider` / `fallback_used` / `fallback_reason`
- Modify: `backend/app/api/v1/endpoints/knowledge_points.py` — 无 ready chunks 时返回业务异常
- Modify: `backend/app/agents/outline.py` — `_fetch_chunks` 返回空时由调用方决定是否阻断
- Modify: `frontend/src/api/chat.ts` — 新增 `listMessages(conversationId)`；`ChatResult` 增加 provider/fallback 字段
- Modify: `frontend/src/components/chat/MessageList.vue` — mock fallback 可见提示
- Modify: `frontend/src/views/ChatView.vue` — `selectConversation` 调用 `listMessages` 回放历史
- Create: `backend/app/tests/test_conversations.py` — 历史接口测试（含跨用户 404）

### Phase 2 (quality)
- Modify: `backend/app/retrieval/search.py` — `keyword_search` 增加标题/材料名加权 + 中文分词注释
- Modify: `README.md` — 检索表述收敛为「关键词检索 + 引用校验」
- Modify: `backend/app/services/multi_scheduler.py` — 接入 WeakPoint 统计；超预算返回 overflow_warnings
- Modify: `backend/app/schemas/plan.py`（或 `multi_plan.py`）— 响应增加 `overflow_warnings`
- Modify: `frontend/src/views/MultiPlanView.vue` — 展示超预算提示
- Create: `backend/app/tests/test_multi_scheduler_weak.py` — 薄弱点权重 + 溢出测试（若无则新建）

### Phase 3 (hardening)
- Modify: `backend/app/core/config.py` — 新增 `CORS_ORIGINS`、`ENVIRONMENT`
- Modify: `backend/app/main.py` — 从配置读 CORS；生产默认密钥检测
- Modify: `backend/.env.example` — 给出正确模板
- Modify: `README.md` — 生产部署注意事项
- Modify: `scripts/verify_phase2_engineering.ps1` — 增加生产密钥检测项

---

## Phase 0: 立即热修 (T01 + T02 + T03)

### Task 1: 修复验收脚本的主观指标残留检查 (T01)

**Files:**
- Modify: `scripts/verify_phase2_engineering.ps1` (lines 34-43)

- [ ] **Step 1: 阅读当前错误的 Select-String 调用**

`f:\course-learning-agent\scripts\verify_phase2_engineering.ps1` 第 37-38 行：

```powershell
$matches = Get-ChildItem -Path $src -Recurse -File |
  Select-String -Pattern '可靠性|相关度|confidencePercent|命中率' -SimpleMatch
```

`-SimpleMatch` 会把整串 `可靠性|相关度|confidencePercent|命中率` 当作字面量字符串查找，无法按「或」匹配。

- [ ] **Step 2: 改为正则匹配（去掉 -SimpleMatch）**

替换为：

```powershell
$matches = Get-ChildItem -Path $src -Recurse -File |
  Select-String -Pattern '可靠性|相关度|confidencePercent|命中率'
```

- [ ] **Step 3: 临时在 frontend/src 放入「相关度」验证脚本能检测到**

在 `frontend/src/views/MaterialsView.vue` 末尾临时加一行注释 `// 相关度测试`，运行脚本应失败（exit 1），删除注释后应通过（exit 0）。

- [ ] **Step 4: 验收**

```powershell
pwsh ./scripts/verify_phase2_engineering.ps1 -SkipBackend
```

期望：无残留时 exit 0；放入残留时 exit 1。

### Task 2: 放开 ready/failed 资料的重新解析入口 (T02)

**Files:**
- Modify: `frontend/src/views/MaterialsView.vue` (lines 499-506)

- [ ] **Step 1: 阅读当前按钮代码**

第 499-506 行：

```vue
<el-button
  size="small"
  type="primary"
  :disabled="row.status !== 'uploaded'"
  @click="handleParse(row)"
>
  解析
</el-button>
```

- [ ] **Step 2: 改为仅 processing 禁用，文案随状态变化**

替换为：

```vue
<el-button
  size="small"
  type="primary"
  :disabled="row.status === 'processing'"
  @click="handleParse(row)"
>
  {{ row.status === 'uploaded' ? '解析' : '重新解析' }}
</el-button>
```

- [ ] **Step 3: 确认 handleParse 已在 Phase 2 bugfix 中刷新 error_message**

阅读 `handleParse`（约 530-560 行）确认：解析后 `await fetchMaterials()`，且 ElMessage 文案已根据 stale-ready 区分。无需再改。

- [ ] **Step 4: 验收**

```powershell
cd frontend; npm run build
```

期望：build 成功，无 TS 错误。

### Task 3: 触发 CI 并保存证据 (T03)

**Files:** 无代码改动，仅 GitHub Actions 操作

- [ ] **Step 1: 确认 ci.yml 已有 workflow_dispatch**

已确认 `.github/workflows/ci.yml` 第 7 行 `workflow_dispatch:` 存在（Phase 2 已加）。

- [ ] **Step 2: 在 Phase 0 提交并 push 后，去 GitHub Actions 页面手动 Run workflow**

URL: https://github.com/dddd2024/course-learning-agent/actions/workflows/ci.yml

- [ ] **Step 3: 记录 backend-test 与 frontend-build 的通过结果**

若失败，按日志修复后重新触发。

- [ ] **Step 4: 提交 Phase 0**

```powershell
git add scripts/verify_phase2_engineering.ps1 frontend/src/views/MaterialsView.vue
git commit -m "fix(phase0): repair acceptance script regex and open reparse entry"
git push origin main
```

---

## Phase 1: 演示闭环修复 (T04 + T05 + T06)

### Task 4: 补对话历史读取与前端回放 (T04)

**Files:**
- Create: `backend/app/schemas/message.py`
- Modify: `backend/app/api/v1/endpoints/conversations.py`
- Modify: `frontend/src/api/chat.ts`
- Modify: `frontend/src/views/ChatView.vue`
- Create: `backend/app/tests/test_conversations.py`

- [ ] **Step 1: 写失败测试 — 历史接口返回 user/assistant 消息**

`backend/app/tests/test_conversations.py`:

```python
import pytest
from app.tests.conftest import auth_headers, create_course


@pytest.mark.asyncio
async def test_list_messages_returns_history(client, db_session, demo_user, demo_course):
    # demo_course 已由 conftest fixture 创建；先创建一个 conversation
    resp = client.post(
        "/api/v1/conversations",
        json={"course_id": demo_course.id, "title": "hist test"},
        headers=auth_headers(demo_user),
    )
    conv_id = resp.json()["id"]
    # 发一条 chat 消息（会产生 user + assistant 两条 Message）
    chat_resp = client.post(
        "/api/v1/chat",
        json={"course_id": demo_course.id, "conversation_id": conv_id, "question": "什么是操作系统？"},
        headers=auth_headers(demo_user),
    )
    assert chat_resp.status_code == 200
    # 拉取历史
    hist = client.get(f"/api/v1/conversations/{conv_id}/messages", headers=auth_headers(demo_user))
    assert hist.status_code == 200
    items = hist.json()["items"]
    assert len(items) >= 2
    assert items[0]["role"] == "user"
    assert items[1]["role"] == "assistant"
    assert "什么是操作系统" in items[0]["content"]


@pytest.mark.asyncio
async def test_list_messages_404_for_other_user(client, db_session, demo_user, other_user, demo_course):
    # demo_user 创建 conversation
    resp = client.post(
        "/api/v1/conversations",
        json={"course_id": demo_course.id, "title": "private"},
        headers=auth_headers(demo_user),
    )
    conv_id = resp.json()["id"]
    # other_user 尝试读取 → 404
    hist = client.get(f"/api/v1/conversations/{conv_id}/messages", headers=auth_headers(other_user))
    assert hist.status_code == 404
```

- [ ] **Step 2: 运行测试，确认失败（接口不存在）**

```powershell
cd backend; python -m pytest app/tests/test_conversations.py -v
```

期望：404 或 ImportError。

- [ ] **Step 3: 创建 message schema**

`backend/app/schemas/message.py`:

```python
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class CitationBrief(BaseModel):
    """历史回放用的精简引用信息（不含 chunk 全文）。"""
    chunk_id: int
    quote_text: Optional[str] = None
    page_no: Optional[int] = None
    material_name: Optional[str] = None
    display_label: Optional[str] = None


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    role: str
    content: Optional[str] = None
    answer_json: Optional[str] = None
    citations: List[CitationBrief] = []
    created_at: datetime


class MessageListResponse(BaseModel):
    items: List[MessageResponse]
    total: int
```

- [ ] **Step 4: 在 conversations.py 新增 GET /conversations/{id}/messages**

在 `backend/app/api/v1/endpoints/conversations.py` 末尾追加：

```python
from app.models.conversation import Conversation, Message
from app.models.citation import Citation
from app.models.material import Material, MaterialChunk
from app.schemas.message import MessageListResponse, MessageResponse, CitationBrief


def _get_owned_conversation(db, conv_id, user_id) -> Conversation:
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if not conv or conv.user_id != user_id:
        raise NotFoundException("对话不存在")
    return conv


@router.get(
    "/{conversation_id}/messages",
    response_model=MessageListResponse,
    summary="获取对话历史消息",
)
def list_messages(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    conv = _get_owned_conversation(db, conversation_id, current_user.id)
    msgs = (
        db.query(Message)
        .filter(Message.conversation_id == conv.id)
        .order_by(Message.id.asc())
        .all()
    )
    items: list[MessageResponse] = []
    for m in msgs:
        cites = (
            db.query(Citation, Material.filename, MaterialChunk.title)
            .join(MaterialChunk, Citation.chunk_id == MaterialChunk.id)
            .join(Material, MaterialChunk.material_id == Material.id)
            .filter(Citation.message_id == m.id)
            .all()
        )
        briefs = []
        for c, filename, chunk_title in cites:
            label = f"{filename} · 第 {c.page_no} 页" if c.page_no else filename
            briefs.append(CitationBrief(
                chunk_id=c.chunk_id,
                quote_text=c.quote_text,
                page_no=c.page_no,
                material_name=filename,
                display_label=label,
            ))
        items.append(MessageResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            answer_json=m.answer_json,
            citations=briefs,
            created_at=m.created_at,
        ))
    return MessageListResponse(items=items, total=len(items))
```

- [ ] **Step 5: 运行测试，确认通过**

```powershell
cd backend; python -m pytest app/tests/test_conversations.py -v
```

- [ ] **Step 6: 前端 chat.ts 新增 listMessages**

在 `frontend/src/api/chat.ts` 追加：

```ts
export interface CitationBrief {
  chunk_id: number
  quote_text?: string | null
  page_no?: number | null
  material_name?: string | null
  display_label?: string | null
}

export interface HistoryMessage {
  id: number
  role: 'user' | 'assistant'
  content?: string | null
  answer_json?: string | null
  citations: CitationBrief[]
  created_at: string
}

export interface HistoryResponse {
  items: HistoryMessage[]
  total: number
}

export function listMessages(conversationId: number) {
  return api.get<HistoryResponse>(`/conversations/${conversationId}/messages`)
}
```

- [ ] **Step 7: 前端 ChatView.vue 的 selectConversation 调用 listMessages 回放历史**

把 `selectConversation` 改为：

```ts
async function selectConversation(conv: Conversation) {
  if (activeConversationId.value === conv.id) return
  activeConversationId.value = conv.id
  messages.value = []
  resetStreamState()
  statusExpanded.value = false
  try {
    const { data } = await listMessages(conv.id)
    messages.value = data.items.map((m): ChatMessage => {
      let citations: Citation[] = []
      let followUpQuestions: string[] = []
      let notFound = false
      let reliabilityLevel: string | undefined
      let retrievedChunks: RetrievedChunk[] = []
      if (m.answer_json) {
        try {
          const parsed = JSON.parse(m.answer_json)
          citations = (parsed.citations ?? []).map((c: any, i: number) => ({
            chunk_id: c.chunk_id,
            material_name: c.material_name ?? m.citations[i]?.material_name ?? '',
            page_no: c.page_no ?? m.citations[i]?.page_no ?? null,
            quote_text: c.quote_text ?? '',
            confidence: c.confidence ?? 0,
            display_label: c.display_label ?? m.citations[i]?.display_label ?? '',
          }))
          followUpQuestions = parsed.follow_up_questions ?? []
          notFound = parsed.not_found ?? false
          reliabilityLevel = parsed.reliability_level
        } catch {
          // answer_json 解析失败时退化为只用 citations 表的数据
          citations = m.citations.map((c) => ({
            chunk_id: c.chunk_id,
            material_name: c.material_name ?? '',
            page_no: c.page_no ?? null,
            quote_text: c.quote_text ?? '',
            confidence: 0,
            display_label: c.display_label ?? '',
          }))
        }
      }
      return {
        role: m.role === 'user' ? 'user' : 'agent',
        content: m.content ?? '',
        messageId: m.id,
        citations,
        followUpQuestions,
        notFound,
        reliabilityLevel,
        retrievedChunks,
        pending: false,
      }
    })
    await nextTick()
    scrollToBottom()
  } catch (err) {
    ElMessage.error(parseApiError(err, '读取历史失败'))
  }
}
```

- [ ] **Step 8: 前端验收**

```powershell
cd frontend; npm run build
```

### Task 5: 显式标记 LLM fallback 与 mock 状态 (T05)

**Files:**
- Modify: `backend/app/agents/llm.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/app/schemas/chat.py`
- Modify: `frontend/src/components/chat/MessageList.vue`
- Modify: `frontend/src/api/chat.ts`

- [ ] **Step 1: 写失败测试 — ChatResponse 含 provider/fallback_used 字段**

在 `backend/app/tests/test_chat.py` 末尾追加：

```python
def test_chat_response_includes_provider_and_fallback(client, db_session, demo_user, demo_course):
    resp = client.post(
        "/api/v1/conversations",
        json={"course_id": demo_course.id, "title": "fallback test"},
        headers=auth_headers(demo_user),
    )
    conv_id = resp.json()["id"]
    chat = client.post(
        "/api/v1/chat",
        json={"course_id": demo_course.id, "conversation_id": conv_id, "question": "测试"},
        headers=auth_headers(demo_user),
    )
    body = chat.json()
    assert "provider" in body
    assert "fallback_used" in body
    # mock 模式下 provider 应为 "mock"
    assert body["provider"] in ("mock", "real")
```

- [ ] **Step 2: 运行测试，确认失败（字段不存在）**

```powershell
cd backend; python -m pytest app/tests/test_chat.py::test_chat_response_includes_provider_and_fallback -v
```

- [ ] **Step 3: 改造 call_llm 返回 provider/fallback 信息**

在 `backend/app/agents/llm.py` 把 `call_llm` 的返回签名从 `dict` 改为 `tuple[dict, dict]`，第二个元素是元信息：

```python
def call_llm(
    prompt: str,
    agent_type: str,
    schema: dict | None = None,
    user_config: dict | None = None,
) -> tuple[dict, dict]:
    """Returns (result, meta) where meta has provider/fallback_used/fallback_reason."""
    # 1. user_config 优先
    if user_config:
        try:
            result = _real_response(prompt, agent_type, schema, user_config)
            return result, {"provider": "real", "fallback_used": False, "fallback_reason": None}
        except Exception as exc:
            logger.warning("user_config LLM call failed: %s; falling back to mock", exc)
            return _mock_response(agent_type), {
                "provider": "mock",
                "fallback_used": True,
                "fallback_reason": str(exc) or exc.__class__.__name__,
            }
    # 2. 系统 provider
    provider = settings.LLM_PROVIDER or "mock"
    if provider == "real":
        try:
            result = _real_response(prompt, agent_type, schema, None)
            return result, {"provider": "real", "fallback_used": False, "fallback_reason": None}
        except Exception as exc:
            logger.warning("real LLM call failed: %s; falling back to mock", exc)
            return _mock_response(agent_type), {
                "provider": "mock",
                "fallback_used": True,
                "fallback_reason": str(exc) or exc.__class__.__name__,
            }
    # 3. mock
    return _mock_response(agent_type), {"provider": "mock", "fallback_used": False, "fallback_reason": None}
```

注意：所有 `call_llm` 的调用方都需要解包。`chat_service.py` 的 `outline.py` / `planner.py` 等调用方都要改成 `result, meta = call_llm(...)`。

- [ ] **Step 4: 更新所有 call_llm 调用方**

在 `chat_service.py`、`outline.py`、`planner.py`、`multi_scheduler.py`、`quiz.py` 等所有调用 `call_llm` 的地方，把 `result = call_llm(...)` 改为 `result, llm_meta = call_llm(...)`。其中 `chat_service.py` 需要把 `llm_meta` 透传到 `ChatResult`。

- [ ] **Step 5: ChatResponse schema 增加 provider/fallback 字段**

在 `backend/app/schemas/chat.py` 的 `ChatResult` 增加：

```python
class ChatResult(BaseModel):
    # ...existing fields...
    provider: str = "mock"
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
```

- [ ] **Step 6: chat_service 透传 meta**

在 `run_chat_pipeline` 内 `result, llm_meta = call_llm(...)` 之后，把 `llm_meta` 字段写入最终返回的 `ChatResult`。

- [ ] **Step 7: 运行测试，确认通过**

```powershell
cd backend; python -m pytest app/tests/test_chat.py app/tests/test_llm.py -v
```

- [ ] **Step 8: 前端 chat.ts 增加 provider/fallback 字段；MessageList 显示提示**

`frontend/src/api/chat.ts` 的 `ChatResult` interface 增加：

```ts
export interface ChatResult {
  // ...existing...
  provider: string
  fallback_used: boolean
  fallback_reason?: string | null
}
```

`frontend/src/components/chat/MessageList.vue` 在 agent 消息气泡内，当 `fallback_used` 为 true 时显示：

```vue
<el-alert
  v-if="message.fallbackUsed"
  type="warning"
  :closable="false"
  show-icon
  class="fallback-alert"
>
  已回退到 mock 模式{{ message.fallbackReason ? `（${message.fallbackReason}）` : '' }}
</el-alert>
```

`ChatView.vue` 的 `applyChatResult` 把 `result.fallback_used` / `result.fallback_reason` 写入 message。

- [ ] **Step 9: 前端验收**

```powershell
cd frontend; npm run build
```

### Task 6: 无 ready chunks 时阻断生成型功能 (T06)

**Files:**
- Modify: `backend/app/api/v1/endpoints/knowledge_points.py`
- Modify: `backend/app/services/chat_service.py`

- [ ] **Step 1: 写失败测试 — 空课程生成知识点返回业务错误**

在 `backend/app/tests/test_knowledge_points.py` 追加：

```python
def test_generate_kp_rejected_when_no_ready_chunks(client, db_session, demo_user):
    # 创建一个空课程（无任何 material）
    resp = client.post(
        "/api/v1/courses",
        json={"name": "空课程", "description": "无资料"},
        headers=auth_headers(demo_user),
    )
    course_id = resp.json()["id"]
    kp = client.post(
        f"/api/v1/courses/{course_id}/knowledge-points/generate",
        headers=auth_headers(demo_user),
    )
    assert kp.status_code in (400, 409)
    assert "资料" in kp.json()["detail"] or "解析" in kp.json()["detail"]
```

- [ ] **Step 2: 运行测试，确认失败**

```powershell
cd backend; python -m pytest app/tests/test_knowledge_points.py::test_generate_kp_rejected_when_no_ready_chunks -v
```

- [ ] **Step 3: knowledge_points.py 增加 ready chunks 守卫**

在 `generate_knowledge_points` 内 `_get_owned_course` 之后、`outline_generate` 之前插入：

```python
from app.models.material import Material, MaterialChunk
from sqlalchemy import select

ready_chunk_count = (
    db.query(MaterialChunk)
    .join(Material, MaterialChunk.material_id == Material.id)
    .filter(Material.course_id == course.id, Material.status == "ready")
    .count()
)
if ready_chunk_count == 0:
    raise HTTPException(
        status_code=400,
        detail="该课程还没有已解析的资料，请先上传并解析材料后再生成知识点。",
    )
```

- [ ] **Step 4: chat_service 在检索结果为空时短路返回 not_found**

在 `run_chat_pipeline` 内 `ranked = rerank(...)` 之后：

```python
if not ranked:
    return ChatResult(
        conversation_id=conversation.id,
        message_id=assistant_msg.id if 'assistant_msg' in locals() else None,
        answer="未检索到与该问题相关的课程资料，请先上传并解析材料后再提问。",
        citations=[],
        not_found=True,
        follow_up_questions=[],
        provider="mock",
        fallback_used=False,
    )
```

注意：需要在写入 user_msg 之后、调用 LLM 之前判断。

- [ ] **Step 5: 运行测试，确认通过**

```powershell
cd backend; python -m pytest app/tests/test_knowledge_points.py app/tests/test_chat_retrieval.py -v
```

- [ ] **Step 6: 前端对 400 业务错误显示友好提示**

`frontend/src/views/KnowledgePointsView.vue`（或对应文件）在 catch 里检查 400 + detail 含「资料」时显示 `ElMessage.warning(detail)`。

- [ ] **Step 7: 验收**

```powershell
cd backend; python -m pytest app/tests/ -v
cd ../frontend; npm run build
```

- [ ] **Step 8: 提交 Phase 1**

```powershell
git add -A
git commit -m "fix(chat): restore conversation history, expose llm fallback state, guard empty courses"
git push origin main
```

---

## Phase 2: 功能质量提升 (T07 + T08)

### Task 7: 检索质量与 RAG 表述收敛 (T07)

**Files:**
- Modify: `backend/app/retrieval/search.py`
- Modify: `README.md`

- [ ] **Step 1: 写失败测试 — 中英文混合查询能命中**

在 `backend/app/tests/test_search.py` 追加：

```python
def test_keyword_search_hits_mixed_cn_en(client, db_session, demo_user, demo_course, ready_chunk):
    # ready_chunk 文本含「快表 TLB 页表」
    results = keyword_search(db_session, demo_course.id, "快表 TLB")
    assert len(results) > 0
    assert any("快表" in r["text"] or "TLB" in r["text"] for r in results)
```

- [ ] **Step 2: 强化 keyword_search — 标题/材料名加权**

在 `keyword_search` 内，score 计算改为：

```python
# 标题命中加权 3x，材料名命中加权 2x，正文命中 1x
score = 0
for kw in keywords:
    kw_l = kw.lower()
    score += chunk.title.lower().count(kw_l) * 3 if chunk.title else 0
    score += material.filename.lower().count(kw_l) * 2
    score += chunk.text.lower().count(kw_l)
```

- [ ] **Step 3: 运行测试，确认通过**

```powershell
cd backend; python -m pytest app/tests/test_search.py -v
```

- [ ] **Step 4: README 表述收敛**

在 `README.md` 把「向量检索」「semantic RAG」等措辞改为「关键词检索 + 引用校验」，并说明 vector_search 为预留接口。

- [ ] **Step 5: 提交 retrieval**

```powershell
git add backend/app/retrieval/search.py README.md backend/app/tests/test_search.py
git commit -m "perf(retrieval): weight title/filename matches and fix RAG wording"
```

### Task 8: 修复多课程计划薄弱点权重与超预算提示 (T08)

**Files:**
- Modify: `backend/app/services/multi_scheduler.py`
- Modify: `backend/app/schemas/plan.py`（或 `multi_plan.py`）
- Modify: `frontend/src/views/MultiPlanView.vue`
- Create/Modify: `backend/app/tests/test_multi_plans.py`

- [ ] **Step 1: 写失败测试 — 薄弱点影响排序 + 超预算有 warning**

在 `backend/app/tests/test_multi_plans.py` 追加：

```python
def test_weak_point_weight_affects_priority(db_session, demo_user):
    # 课程 A 有错题薄弱点，课程 B 没有；同样 deadline
    # → A 的 priority_score 应高于 B
    ...

def test_overflow_returns_warning(client, db_session, demo_user):
    # daily_minutes=30，但任务总量 200 分钟 → response 含 overflow_warnings
    ...
```

- [ ] **Step 2: 实现 WeakPoint 统计**

在 `multi_scheduler.py` 把 `weak_point_weight=0.0` 改为：

```python
from app.models.weak_point import WeakPoint  # 按实际模型路径

def _compute_weak_point_weight(db, course_id, max_wrong=1.0) -> float:
    total_wrong = (
        db.query(func.sum(WeakPoint.wrong_count))
        .filter(WeakPoint.course_id == course_id)
        .scalar()
    ) or 0
    return min(1.0, total_wrong / max_wrong) if max_wrong > 0 else 0.0
```

调用：`weak_point_weight = _compute_weak_point_weight(db, cp["course_id"])`。

- [ ] **Step 3: 超预算时收集 overflow_warnings**

在 fallback 分支（任务被塞到最后一天）记录：

```python
overflow_warnings.append(
    f"课程「{cp['course_name']}」的任务无法在每日预算内安排，已放到截止日前最后一天，可能超出预算。"
)
```

返回结构增加 `overflow_warnings: list[str]`。

- [ ] **Step 4: 前端 MultiPlanView 展示 warning**

```vue
<el-alert
  v-for="(w, i) in plan.overflow_warnings"
  :key="i"
  type="warning"
  :closable="false"
  show-icon
>{{ w }}</el-alert>
```

- [ ] **Step 5: 验收**

```powershell
cd backend; python -m pytest app/tests/test_multi_plans.py app/tests/test_plans.py -v
cd ../frontend; npm run build
```

- [ ] **Step 6: 提交 scheduler**

```powershell
git add -A
git commit -m "fix(scheduler): use weak-point weight and surface overflow warnings"
git push origin main
```

---

## Phase 3: 工程硬化 (T09)

### Task 9: 安全配置与生产环境硬化 (T09)

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/main.py`
- Modify: `backend/.env.example`
- Modify: `README.md`
- Modify: `scripts/verify_phase2_engineering.ps1`

- [ ] **Step 1: 写失败测试 — 生产环境默认密钥应启动失败**

在 `backend/app/tests/test_health.py` 追加：

```python
def test_prod_rejects_default_jwt_secret(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "change_me")
    monkeypatch.setenv("LLM_CONFIG_SECRET_KEY", "change-me-please")
    from app.core.config import Settings
    s = Settings()
    with pytest.raises(ValueError, match="默认密钥"):
        s.validate_prod_secrets()
```

- [ ] **Step 2: config.py 增加 CORS_ORIGINS、ENVIRONMENT、validate_prod_secrets**

```python
class Settings(BaseSettings):
    # ...existing...
    ENVIRONMENT: str = "development"  # development | production
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    def validate_prod_secrets(self) -> None:
        if self.ENVIRONMENT != "production":
            return
        if self.JWT_SECRET_KEY in ("change_me", ""):
            raise ValueError("生产环境不能使用默认 JWT_SECRET_KEY")
        if self.LLM_CONFIG_SECRET_KEY in ("change-me-please", ""):
            raise ValueError("生产环境不能使用默认 LLM_CONFIG_SECRET_KEY")
```

- [ ] **Step 3: main.py 从配置读 CORS + 启动时校验**

```python
from app.core.config import settings

# 启动时校验生产密钥
settings.validate_prod_secrets()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- [ ] **Step 4: 更新 .env.example**

```env
ENVIRONMENT=development
JWT_SECRET_KEY=please-change-this-to-a-random-long-string
LLM_CONFIG_SECRET_KEY=please-change-this-too
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
LLM_PROVIDER=mock
```

- [ ] **Step 5: README 增加生产部署注意事项**

新增「生产部署」小节，说明密钥、CORS、上传目录、数据库迁移。

- [ ] **Step 6: 验收脚本增加生产密钥检测项**

在 `verify_phase2_engineering.ps1` 增加：检查 `config.py` 中 `CORS_ORIGINS` 不为 `"*"`、`main.py` 不再硬编码 `allow_origins=["*"]`。

- [ ] **Step 7: 运行测试**

```powershell
cd backend; python -m pytest app/tests/ -v
cd ../frontend; npm run build
pwsh ./scripts/verify_phase2_engineering.ps1
```

- [ ] **Step 8: 提交 Phase 3**

```powershell
git add -A
git commit -m "hardening(config): env-driven cors and prod secret validation"
git push origin main
```

---

## 全量验收清单（最终）

完成所有阶段后按顺序执行，任何一步失败都不进入下一步：

1. 后端单元测试：`cd backend && python -m pytest app/tests/ -v`
2. 前端构建：`cd frontend && npm run build`
3. 验收脚本：`pwsh ./scripts/verify_phase2_engineering.ps1`
4. 手动演示 1：上传资料 → 解析 → 检索 → 提问 → 打开引用证据抽屉
5. 手动演示 2：ready 资料重新解析失败 → 状态显示「已就绪（上次解析失败）」→ 旧片段仍可查看
6. 手动演示 3：创建两个对话 → 切换对话 → 历史消息正确回放
7. 手动演示 4：无 ready chunks 的课程不能生成误导性知识点或固定 mock 答案
8. GitHub Actions：backend-test 与 frontend-build 均有通过记录

## 提交策略

| 阶段 | 提交信息 | 任务 |
|------|----------|------|
| 0 | `fix(phase0): repair acceptance script regex and open reparse entry` | T01, T02, T03 |
| 1 | `fix(chat): restore conversation history, expose llm fallback state, guard empty courses` | T04, T05, T06 |
| 2a | `perf(retrieval): weight title/filename matches and fix RAG wording` | T07 |
| 2b | `fix(scheduler): use weak-point weight and surface overflow warnings` | T08 |
| 3 | `hardening(config): env-driven cors and prod secret validation` | T09 |

## 暂不纳入本轮的事项

- 最终课程报告、答辩 PPT、截图排版
- 完整向量数据库、复杂 embedding 管线和大规模 Alembic 迁移
- 一键演示脚本、Docker Compose 生产部署、权限角色系统
- 句级 citation quote_start/quote_end、资料版本树、复杂错题闭环
