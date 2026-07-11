# V3 基线验证计划 (BASE-V3-01)

> **任务编号:** BASE-V3-01
> **状态:** 活跃
> **基线提交:** 819da49 (main 分支, CI #28914666690 已 success)
> **创建日期:** 2026-07-11

---

## 1. 目标

本文档定义 V3 质量收尾 (Quality Closure) 的基线验证计划。目标是确保
跨课程知识图谱 v3 收尾阶段的五项质量标准在代码库中持续满足，并提供
自动化脚本以在任何时间点复验。

V3 收尾工作基于 `concept-graph-v3-closure` 规格完成，核心交付物包括:

- evidence_hash 按证据内容计算 (而非仅 chunk_id)
- 旧库列迁移器 (无 Alembic, 启动即兼容)
- CI 证据归档文档
- 验收脚本行为化补强
- user_focus 枚举约束

本基线验证脚本在此基础上增加五项质量门禁检查，防止回归。

---

## 2. 验证脚本

### 2.1 Python 脚本

**文件:** `scripts/verify_quality_closure_v3.py`

脚本使用 Python 标准库 (`pathlib`, `re`, `subprocess`, `json`) 实现，
不依赖外部包。通过 `subprocess` 调用后端 venv 中的 pytest，通过文件
读取 (`Path.read_text`) 和正则表达式执行代码静态检查。

**运行方式:**

```bash
# 全量运行 (控制台输出 + JSON 摘要)
python scripts/verify_quality_closure_v3.py

# 仅输出 JSON (适用于 CI)
python scripts/verify_quality_closure_v3.py --json

# 运行单个检查
python scripts/verify_quality_closure_v3.py --check no_hardcoded_quiz
```

**退出码:** 0 = 全部通过, 1 = 存在失败, 2 = 未知检查名

### 2.2 PowerShell 包装器

**文件:** `scripts/verify_quality_closure_v3.ps1`

PowerShell 包装器自动定位后端 venv 中的 Python 解释器，设置工作目录，
并调用 Python 脚本。支持 `-JsonOnly` 和 `-Check` 参数。

**运行方式:**

```powershell
pwsh -NoProfile -File scripts/verify_quality_closure_v3.ps1
pwsh -NoProfile -File scripts/verify_quality_closure_v3.ps1 -Check no_hardcoded_quiz
```

---

## 3. 检查项详解

### 检查 1: 无硬编码测验内容 (`no_hardcoded_quiz`)

**检查 ID:** `no_hardcoded_quiz`

**目的:** 确保 `backend/app/agents/` 目录下的 Python 源码不包含
硬编码的 "梯度下降" 测验内容。

**背景:** V3 之前，`llm.py` 中的 `_mock_quiz_generate` 函数返回固定的
"梯度下降更新参数的方向是？" 测验题目，与实际课程资料无关。V3 要求
mock builder 从 prompt 中的证据片段派生内容，因此该字面值不得出现在
agent 源码中 (注释/docstring 中的描述性引用除外)。

**检查方法:**
- 读取 `backend/app/agents/*.py` 的每个文件
- 逐行搜索 "梯度下降" 字符串
- 排除: 纯注释行 (`#`), docstring 行 (`"""`/`'''`), 以及包含
  "hardcoded" 或 "instead of" 的描述性引用行
- 仅当字符串出现在代码行的引号内时判定为违规

**通过条件:** 无违规行

**失败示例:**
```json
{
  "check": "no_hardcoded_quiz",
  "status": "fail",
  "message": "Found 1 hardcoded '梯度下降' reference(s) in agent code",
  "details": {
    "violations": [
      {
        "file": "backend/app/agents/llm.py",
        "line": 678,
        "snippet": "\"stem\": \"梯度下降更新参数的方向是？\","
      }
    ]
  }
}
```

---

### 检查 2: 无直接 finish_run(status="success") 调用 (`no_direct_success_finish`)

**检查 ID:** `no_direct_success_finish`

**目的:** 确保 agent 文件不直接调用 `AgentAudit.finish_run(status="success")`，
而是通过 `_safe_finish_run` / `finalize_run` 包装器间接调用。

**背景:** `AgentAudit.finish_run` 直接调用时，如果审计 DB 写入失败
(例如连接异常)，异常会向上传播并中断主流程。`_safe_finish_run` 包装器
捕获并吞掉审计异常，保证审计失败不影响业务流程。所有 agent 必须使用
包装器模式。

**检查方法:**
- 读取 `backend/app/agents/*.py` 的每个文件
- 用正则匹配 `AgentAudit.finish_run(` 或裸 `finish_run(` 调用
- 在调用窗口 (当前行 + 后 5 行) 内搜索 `status="success"` 或
  `status='success'`
- 排除: 位于 `_safe_finish_run` 函数定义内部的调用 (包装器本身允许
  直接调用)

**通过条件:** 无违规的直接调用

---

### 检查 3: V3 测试文件存在 (`v3_tests_exist`)

**检查 ID:** `v3_tests_exist`

**目的:** 确保 V3 收尾所需的关键测试文件存在于磁盘上。

**检查文件:**
| 文件 | 说明 |
|------|------|
| `test_concept_compare_agent.py` | 概念对比 agent 行为测试 (缓存失效、证据加载等) |
| `test_concept_graph_api.py` | 概念图谱 API 测试 (user_focus 枚举校验、mismatched edge) |
| `test_db_migrations.py` | 轻量列迁移器测试 (旧库兼容) |

此外，脚本还会通过 glob 模式 `test_v3_*.py` 自动发现并登记以下文件:

| 文件 | 说明 |
|------|------|
| `test_v3_agent_status.py` | Agent 运行状态降级测试 (BASE-V3-02) |
| `test_v3_evidence_gate.py` | 证据门禁测试 |
| `test_v3_plan_execution.py` | 计划执行测试 |
| `test_v3_quiz_grounding.py` | 测验证据溯源测试 |

**通过条件:** 三个必需 V3 测试文件全部存在 (glob 发现的 test_v3_*.py 为附加登记)

---

### 检查 4: V3 测试通过 (`v3_tests_pass`)

**检查 ID:** `v3_tests_pass`

**目的:** 运行 V3 测试文件，确保全部通过。

**检查方法:**
- 使用后端 venv 的 Python (`backend/.venv/Scripts/python.exe`) 执行
  `python -m pytest app/tests/{test_file} -q --tb=short`
- 检查退出码是否为 0

**通过条件:** pytest 退出码为 0

---

### 检查 5: V3 关键测试通过 (`v3_key_tests_pass`)

**检查 ID:** `v3_key_tests_pass`

**目的:** 显式运行 V3 收尾的核心行为测试，确保关键路径不回归。

**关键测试 node-ids:**
| 测试 | 说明 |
|------|------|
| `test_concept_compare_agent.py::test_compare_cache_invalidates_when_evidence_text_changes` | 证据内容变化时缓存失效 |
| `test_concept_compare_agent.py::test_compare_rejects_mismatched_edge_id` | 拒绝不匹配的 edge_id |
| `test_concept_graph_api.py::test_compare_invalid_user_focus_returns_422` | 非法 user_focus 返回 422 |
| `test_concept_graph_api.py::test_compare_mismatched_edge_returns_400` | 不匹配 edge 返回 400 |

**通过条件:** pytest 退出码为 0

---

### 检查 6: 引用 support_status 支持非 weak 值 (`citation_support_status`)

**检查 ID:** `citation_support_status`

**目的:** 确保正式引用 (携带 quote_text + claim_text) 可以被标记为
"verified"，而非被锁定为 "weak"。

**检查内容:**
1. **模型层:** `Citation` 模型 (`models/citation.py`) 包含
   `support_status` 字段
2. **Schema 层:** `CitationResponse` schema (`schemas/citation.py`)
   包含 `support_status` 字段
3. **Agent 层:** `course_qa.py` agent 包含 `"verified"` 字符串引用
4. **赋值验证:** `course_qa.py` 中存在
   `support_status = "verified"` 赋值语句 (非仅比较)

**通过条件:** 四项全部满足

**设计理由:** V3 要求引用验证可将通过支撑检查的引用从 "weak" 提升为
"verified"。如果 agent 仅引用但从不赋值 "verified"，正式引用将永远
停留在 "weak" 状态。

---

### 检查 7: 测验项携带源证据 (`quiz_source_evidence`)

**检查 ID:** `quiz_source_evidence`

**目的:** 确保测验题目关联到课程资料证据块 (含文本内容)，防止
生成无溯源依据的"权威"题目。

**检查内容:**
1. **模型层:** `QuizItem` 模型 (`models/quiz.py`) 包含
   `source_evidence_ids` 和 `evidence_snapshot` 字段
2. **验证逻辑:** quiz agent (`agents/quiz.py`) 包含
   `_valid_evidence_ids` 函数，验证证据 ID 对应真实 MaterialChunk
3. **跳过逻辑:** agent 在 `if not evidence_ids:` 时执行
   `continue`/`skip`，丢弃无证据的题目
4. **证据格式化:** agent 包含 `_format_evidence` 函数，且函数体
   引用 `r.text` / `.text` (将 chunk 文本传入 prompt)
5. **字段填充:** agent 在构建 item dict 时包含 `source_evidence_ids`

**通过条件:** 五项全部满足

---

## 4. JSON 输出格式

脚本在 stdout 输出 JSON 摘要，结构如下:

```json
{
  "task": "BASE-V3-01",
  "total_checks": 7,
  "passed": 7,
  "failed": 0,
  "checks": [
    {
      "check": "no_hardcoded_quiz",
      "status": "pass",
      "message": "No hardcoded '梯度下降' quiz content in agents",
      "details": {}
    },
    {
      "check": "no_direct_success_finish",
      "status": "pass",
      "message": "No direct finish_run(status='success') calls in agents",
      "details": {}
    }
  ]
}
```

每个检查结果包含:
- `check`: 检查 ID
- `status`: `"pass"` 或 `"fail"`
- `message`: 人类可读的结果描述
- `details`: 检查细节 (违规列表、文件路径等)

---

## 5. CI 集成建议

### 5.1 GitHub Actions

在 `.github/workflows/ci.yml` 的 Acceptance Script job 中添加:

```yaml
- name: V3 Quality Closure Verification
  run: python scripts/verify_quality_closure_v3.py --json
```

或在 PowerShell 验收脚本中添加:

```powershell
# V3 quality closure
Write-Step 'V3 quality closure'
& $python scripts/verify_quality_closure_v3.py --json
if ($LASTEXITCODE -eq 0) { Write-Ok 'v3 quality closure passed' }
else { Write-Bad 'v3 quality closure failed' }
```

### 5.2 本地开发

开发者在提交前运行:

```bash
python scripts/verify_quality_closure_v3.py
```

或通过 PowerShell:

```powershell
pwsh -NoProfile -File scripts/verify_quality_closure_v3.ps1
```

---

## 6. 检查项与 V3 规格的映射

| 检查项 | V3 规格章节 | 关联 Task |
|--------|-----------|-----------|
| no_hardcoded_quiz | 5.1 内容质量 | 质量门禁 |
| no_direct_success_finish | 5.4 验收脚本行为化 | 工程规范 |
| v3_tests_exist | 完成标准 | Task 1-5 交付物 |
| v3_tests_pass | 完成标准 | Task 6 全量验证 |
| v3_key_tests_pass | 5.4 验收脚本行为化 | Task 5 |
| citation_support_status | 5.1 内容质量 | 引用验证 |
| quiz_source_evidence | 5.1 内容质量 | 测验证据绑定 |

---

## 7. 故障排查

### 7.1 pytest 未找到后端 venv

如果脚本报 "No Python interpreter found"，确认:

```bash
ls backend/.venv/Scripts/python.exe
```

如果 venv 不存在，创建:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 7.2 检查 1 误报

如果 `no_hardcoded_quiz` 检查在注释行误报，确认该行不以 `#` 开头
且不包含 "hardcoded" 或 "instead of" 关键词。脚本会排除这些描述性
引用行。

### 7.3 检查 2 误报

如果 `no_direct_success_finish` 在 `_safe_finish_run` 函数内误报，
确认函数定义行匹配 `def _safe_finish_run`。脚本会回溯 15 行查找
函数定义，匹配则跳过。

### 7.4 测试超时

pytest 默认超时为 300 秒 (5 分钟)。如果测试超时，检查是否有测试
依赖外部服务 (真实 LLM API)。V3 测试应在 mock 模式下运行，不需要
网络访问。

---

## 8. 版本历史

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-07-11 | 1.0 | 初始版本 (BASE-V3-01) |
