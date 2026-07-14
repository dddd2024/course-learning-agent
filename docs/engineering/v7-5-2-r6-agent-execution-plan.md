# V7.5.2 R6 Agent 执行计划：严格验收、证据可复核与 PR #11 收口

## 0. 文档定位

本文件是下一轮 Agent 的直接执行计划，只处理代码、测试、验收与证据收口，不处理课程最终报告、演示文稿或其他文书。

当前工作对象：

- 仓库：`dddd2024/course-learning-agent`
- 分支：`codex/v7-5-2-r6-audit-fixes`
- Draft PR：`#11 fix(v7.5.2): correct R6 acceptance audit gaps`
- 分支必须包含提交 `27baf75019a8513b3319571053748fcbb0efa3e8`；执行时以远端分支最新 HEAD 为准。
- PR 基线：`main`，创建 PR 时的 base SHA 为 `4cd1d2d2bfe6db49f370f7cfa9a7cba15bb1ba84`。

本计划优先于 R5 中已经被 R6 审计推翻的“RC3 已关闭”表述。旧的 `r5-c1-a9`、`r5-c1-b` 只能作为历史记录，不能作为本轮发布证据。

---

## 1. 总目标

在不扩大产品范围的前提下，将 PR #11 从“已修复明显代码问题但尚未验证”的 Draft 状态推进到“所有本地质量门禁通过、两轮真实模型验收绑定同一冻结代码 SHA、证据能够在仓库中独立复核、远程 CI 通过”的状态。

最终必须同时满足：

1. 真实 LLM 验收只接受显式持久化的真实元数据，不推导、不补全、不类型偷换。
2. 知识点二次修复是课程通用逻辑，并能验证来源原文确实支持修复结果。
3. REAL-03、REAL-05 等验收场景不能通过弱断言或表面字段规避。
4. 所有标准 mock 门禁与完整回归通过，且无跳过测试。
5. 两轮真实模型验收运行在同一冻结代码提交上。
6. 每轮生成可校验的脱敏证据包和 SHA-256 manifest。
7. 证据提交与代码提交严格分离；证据提交不得修改生产代码、测试逻辑或验收脚本。
8. PR #11 在远程 CI 通过前保持 Draft；不得直接合并、创建 tag 或声明 RC3 完成。

---

## 2. 强制约束

### 2.1 Git 与分支约束

- 只能在 `codex/v7-5-2-r6-audit-fixes` 工作。
- 不得直接向 `main` push。
- 不得重写已有远端历史，除非用户明确要求。
- 不得合并 PR #11，不得创建或移动 RC tag。
- 每次开始工作和每个关键阶段后都执行并记录：

```bash
git rev-parse --show-toplevel
git branch --show-current
git rev-parse HEAD
git status --short
git diff --check
```

- 若工作区包含无法归因的用户修改，不得覆盖；先停止并报告。

### 2.2 范围约束

不得修改以下范围，除非其测试明确证明 R6 改动造成回归且修复不可避免：

- Windows 一键启动、桌面快捷方式、launcher 相关文件；
- 与 R6 无关的前端功能；
- 历史文档浏览、bbox 高亮、高级版面恢复等已延期到 v1.1 的功能；
- 课程最终报告及展示文档。

### 2.3 验收真实性约束

严禁通过以下方式“让测试通过”：

- 把 `None`、缺失值转换成合法成功值；
- 根据 provider/model 推导 `meta_observed=true`；
- 降低场景数量、删除失败断言或放宽为只检查关键词；
- 将真实模型失败回退到 mock 后继续记为成功；
- 用规则模板生成知识点冒充真实模型修复；
- 修改验收 fixture 以绕过产品缺陷；
- 跳过测试、增加无理由 `xfail`/`skip`、只运行子集后宣称完整通过；
- 只修改状态 JSON 或测试期望来宣称功能完成。

### 2.4 密钥与证据约束

- API key 只能从进程环境变量读取。
- 禁止将 key 放入命令行参数、仓库 `.env`、日志、异常正文或 committed artifact。
- 禁止提交原始 provider 响应正文。
- 任何 secret scan 命中都必须使该轮失败；不得手工把结果改为 passed。

---

## 3. 执行顺序概览

必须按以下顺序执行，不允许在代码尚未冻结时提前生成正式真实模型证据：

1. R6-00：基线确认与现有改动审查。
2. R6-01：修复或补齐严格元数据验收回归测试。
3. R6-02：完成通用知识点修复的来源语义验证。
4. R6-03：实现真实模型证据 manifest 与独立校验器。
5. R6-04：运行针对性测试和完整本地门禁。
6. R6-05：生成代码冻结提交 C1。
7. R6-06：在 C1 上连续运行两轮真实 LLM 验收。
8. R6-07：生成并验证仓库内脱敏证据包。
9. R6-08：生成仅含状态、文档和证据的 C2。
10. R6-09：推送、等待远程 CI、更新 PR 状态；不合并。

任何阶段失败，都必须保持 `overall_status=in_progress`、`release_candidate=null`。

---

# 4. 详细任务

## R6-00：基线确认与现有修复审查

### 目标

确认 Agent 接手的是 PR #11 当前分支，而不是 `main`、旧 R5 分支或本地过期副本。

### 操作

1. 拉取远端并切换到 `codex/v7-5-2-r6-audit-fixes`。
2. 确认 HEAD 包含以下 R6 直接修复：
   - `scripts/verify_real_llm_acceptance.py` 不再推导 `meta_observed`；
   - 不再使用 `bool(run.get("fallback_used"))`；
   - REAL-03 要求 `not_found=true`、无 citation、拒答正文受限；
   - REAL-05 要求真实 `learn -> material` 任务；
   - `outline_repair_v1.md` 不包含 CRC、停止等待、滑动窗口；
   - `docs/engineering/v7-execution-state.json` 为 `in_progress`；
   - `backend/app/tests/test_r6_acceptance_harness.py` 存在。
3. 查看 PR #11 相对 `main` 的完整 diff，确认没有意外修改 launcher 或其他无关模块。
4. 运行：

```bash
python -m py_compile scripts/verify_real_llm_acceptance.py
python -m pytest backend/app/tests/test_r6_acceptance_harness.py backend/app/tests/test_real_llm_acceptance_service.py backend/app/tests/test_v7_5_2_execution_state.py -q
```

### 完成条件

- 分支、基线和文件范围正确；
- 针对性测试能够收集并运行；
- 若失败，先修复真实问题，不进入完整门禁。

---

## R6-01：严格元数据链路闭环

### 目标

证明真实模型 AgentRun 从调用层、业务层、审计持久化到验收脚本的字段是一条真实、显式、不可推导的链路。

### 检查范围

重点检查：

- `backend/app/agents/llm.py`
- `backend/app/agents/course_qa.py`
- `backend/app/agents/outline.py`
- `backend/app/agents/quiz.py`
- planner 与 material overview 的真实模型调用路径
- `AgentAudit.update_run_meta` 与 AgentRun schema/list endpoint
- `backend/app/services/real_llm_acceptance_service.py`
- `scripts/verify_real_llm_acceptance.py`

### 必须满足的持久化字段

每个需要真实模型审计的 AgentRun 必须能够从 API 读取到：

```json
{
  "status": "success",
  "actual_provider": "非 mock、非 unknown 的显式值",
  "actual_model": "非空显式值",
  "fallback_used": false,
  "output_summary": {
    "meta_observed": true
  }
}
```

不得通过 `provider`、`model_name` 或配置预期补出上述实际字段。

### 必须增加或保留的测试

1. `meta_observed` 缺失但 provider/model 存在：失败。
2. `fallback_used=None`：失败，错误码为 `REAL_LLM_FALLBACK_STATE_MISSING`。
3. `status=degraded`：失败。
4. `status` 缺失或非 `success`：失败。
5. `actual_provider=mock/unknown/空值`：失败。
6. `actual_model` 为空：失败。
7. 显式完整元数据：通过。
8. list-only 兼容分支不能伪造成真实模型成功。

### 完成条件

- 所有真实模型路径使用同一严格契约；
- 验收脚本只读取持久化事实；
- 不存在 `bool(None)`、字段推导或默认成功值。

---

## R6-02：通用知识点修复的来源语义验证

### 背景

当前共享修复 Prompt 已经移除数据链路层专用术语，但修复结果仍需要更强的来源支持校验。仅验证 `chunk_id` 存在，不能阻止模型输出与该 chunk 无关的标题。

### 目标

只强化“真实模型二次修复路径”，不重写整个知识点生成系统。修复结果必须包含可逐字核验的来源原文，且只有被原文支持的知识点才能进入最终结果。

### 实现要求

#### 1. 扩展修复 Prompt 输出结构

在 `outline_repair_v1.md` 中，为每个知识点增加：

```json
{
  "source_evidence": [
    {
      "chunk_id": 123,
      "quote_text": "资料中实际存在的短句"
    }
  ]
}
```

要求：

- 每条知识点至少一个 evidence；
- `chunk_id` 必须是资料中展示的真实数字 ID；
- `quote_text` 必须逐字来自该 chunk；
- 不允许用标题、章节名或空字符串冒充证据；
- 不允许输出外部知识。

#### 2. 在 `_repair_results` 中验证原文

实现一个小而明确的验证函数，至少完成：

- 规范化数字或字符串形式的 chunk ID；
- chunk 必须存在于本次输入资料；
- `quote_text` 去除首尾空白后不能为空；
- 允许统一连续空白后做子串匹配，但不得做模糊语义猜测；
- evidence 中的 chunk ID 必须同时属于该 point 的 `source_chunk_ids`，或直接由通过验证的 evidence 集合生成最终 `source_chunk_ids`；
- 无有效 evidence 的 point 直接丢弃；
- 不得自动绑定所有可用 chunk；
- 不得规则生成替代知识点。

建议最终以“验证通过的 evidence chunk IDs”作为修复 point 的最终来源集合，避免保留未经证据确认的 raw ID。

#### 3. 扩展 contract 统计

`repair_contract` 至少记录：

```json
{
  "valid_count": 2,
  "missing_source_count": 0,
  "unsupported_evidence_count": 0,
  "duplicate_title_count": 0,
  "distinct_source_count": 2,
  "passed": true
}
```

`passed` 必须要求 `unsupported_evidence_count == 0`。

#### 4. 保持失败语义

- 一次修复仍不满足 contract：返回明确失败，不得生成规则 fallback。
- 重新生成失败时必须保留原有 active knowledge points。
- 第一次生成失败不得持久化无证据知识点。

### 测试要求

至少增加以下 fixture 测试：

1. **高等数学资料**：导数与定积分两个小节，能生成两个独立、带真实 quote 的知识点。
2. **数据库资料**：范式与事务两个小节，能生成两个独立知识点。
3. **跨课程污染**：数学 chunk 的合法 ID 配合“滑动窗口协议”标题和无关 quote，必须被拒绝。
4. **伪造 quote**：chunk ID 合法但 quote 不存在，必须被拒绝。
5. **字符串 ID**：`"123"`、`"chunk_id=123"` 可按既有规范精确归一化。
6. **重复标题**：仍然拒绝。
7. **已有提纲保护**：修复失败后旧 active generation 不变。
8. Prompt 静态测试：共享 Prompt 不得重新出现 CRC、停止等待、滑动窗口等 fixture 专用词。

### 完成条件

- 共享修复逻辑可用于任意课程；
- 不相关标题即使绑定合法 chunk ID 也不能依靠 ID 存在性通过；
- 修复失败保持显式失败和旧数据安全。

---

## R6-03：真实模型证据 manifest 与独立校验器

### 目标

让每一轮真实模型验收产生可复核、可检测篡改、可绑定代码 SHA 的证据，而不是只在状态文档里写“6/6 passed”。

### 3.1 每轮本地完整 artifact

保持每轮目录：

```text
artifacts/verification/real-llm/<run-id>/
```

至少包含：

```text
real-llm-acceptance.json
scenario-results.json
redacted-agent-runs.json
environment-fingerprint.json
request-summary.json
logs/backend.redacted.log
logs/worker.redacted.log
evidence-manifest.json
```

### 3.2 `evidence-manifest.json` 结构

至少包含：

```json
{
  "schema_version": 1,
  "run_id": "r6-c1-a",
  "tested_code_sha": "完整 C1 SHA",
  "generated_at": "UTC ISO-8601",
  "provider": "openai-compatible",
  "base_url_host": "仅 scheme + host",
  "model": "实际模型名",
  "scenario_count": 6,
  "passed": 6,
  "audited_agent_run_count": 5,
  "fallback_count": 0,
  "mock_count": 0,
  "degraded_count": 0,
  "meta_missing_count": 0,
  "secret_scan_status": "passed",
  "files": {
    "real-llm-acceptance.json": {
      "sha256": "...",
      "size_bytes": 123
    }
  }
}
```

manifest 不哈希自身，避免循环依赖。

### 3.3 生成顺序

必须保持事务性：

1. 在 staging 目录写入脱敏数据与日志；
2. 运行第一次 secret scan；
3. 将真实 scan 结果写入 summary；
4. 计算除 manifest 自身以外全部文件的 SHA-256 和大小；
5. 写入 manifest；
6. 对包含 manifest 的完整 staging 目录再次做 secret scan；
7. 任一 scan 失败：该轮失败，删除 staging，不得移动为成功 artifact；
8. 全部成功后原子移动到最终目录。

### 3.4 独立校验脚本

新增或扩展脚本，例如：

```text
scripts/verify_real_llm_evidence.py
```

接口示例：

```bash
python scripts/verify_real_llm_evidence.py \
  --artifact-dir artifacts/verification/real-llm/r6-c1-a \
  --expected-sha <C1_SHA>
```

必须验证：

- manifest 与目录文件集合一致；
- 每个文件哈希和大小一致；
- `tested_code_sha == expected_sha`；
- summary `all_passed=true`；
- 6 个场景全部 passed；
- 恰好 5 个需要真实模型的 AgentRun；
- 每个 AgentRun `status=success`、`meta_observed=true`、`fallback_used=false`；
- mock/fallback/degraded/meta-missing 均为 0；
- secret scan 为 passed；
- 缺文件、改动一个字节、错误 SHA、伪造计数均返回非零状态。

### 3.5 校验器测试

至少覆盖：

- 完整合法目录通过；
- 修改 scenario 文件后哈希失败；
- 删除文件失败；
- 增加未列入 manifest 的证据文件失败；
- expected SHA 不一致失败；
- `fallback_used=null` 失败；
- 场景数不是 6 失败；
- audited run 不是 5 失败。

---

## R6-04：本地完整门禁

所有代码完成后，先运行针对性测试，再运行与 CI 对齐的完整门禁。所有命令必须在仓库根目录执行或明确切换目录。

### 4.1 Python 静态编译与针对性测试

```bash
python -m py_compile scripts/verify_real_llm_acceptance.py
python -m py_compile scripts/verify_real_llm_evidence.py
python -m pytest \
  backend/app/tests/test_r6_acceptance_harness.py \
  backend/app/tests/test_real_llm_acceptance_service.py \
  backend/app/tests/test_r5_outline_repair.py \
  backend/app/tests/test_v7_5_2_execution_state.py \
  -q
```

将新增的 outline evidence 测试和 manifest 校验测试加入上述 focused gate。

### 4.2 Backend 全量

严格对齐 CI：

```bash
LLM_PROVIDER=mock python -m pytest backend/app/tests -q
```

要求：

- 退出码 0；
- failed=0；
- skipped=0；
- 记录精确 passed 数量，不得写模糊的“测试通过”。

### 4.3 Frontend

`frontend/package.json` 已定义：`type-check`、`test`、`test:e2e`、`build`。执行：

```bash
cd frontend
npm ci
npm run type-check
npm run test
npm run build
cd ..
```

要求无失败、无 skipped。

### 4.4 Migration

使用独立临时数据库，严格对齐 `.github/workflows/ci.yml`：

```bash
python scripts/migrate.py --dry-run --json artifacts/r6/migration-dry-run.json
python scripts/test_migration.py
```

执行前设置唯一 `DATABASE_URL` 和 `PYTHONPATH=<repo>/backend`，不得使用开发者常用数据库。

### 4.5 Playwright

使用唯一隔离运行目录和 mock provider，执行：

```bash
cd frontend
npm run test:e2e
cd ..
```

随后读取 `frontend/playwright-results.json`，必须满足：

```text
unexpected = 0
skipped = 0
```

不能只依赖命令退出码。

### 4.6 V7 Acceptance

严格对齐 CI：

```bash
python scripts/verify_function_closure_v7.py \
  --artifact-root artifacts \
  --external-e2e frontend/playwright-results.json
```

必须验证生成的 `v7-acceptance.json`：

- `version == "v7"`；
- `all_passed == true`；
- 每个 check `status == "pass"`；
- `total_checks == len(checks)`；
- 无 skipped。

### 4.7 失败处理

任何门禁失败：

- 修复代码或测试环境的真实问题；
- 重新运行受影响的 focused tests；
- 再重新运行全量门禁；
- 不得进入 C1 冻结；
- 状态文件保持 `in_progress`。

---

## R6-05：代码冻结提交 C1

### 目标

建立真实模型验收唯一绑定的代码提交。

### C1 内容

可以包含：

- 生产代码；
- Prompt；
- 验收脚本；
- manifest 生成/校验脚本；
- 测试；
- 必要的技术文档与计划状态更新。

不得包含正式真实模型运行结果，因为运行必须在冻结后执行。

### 提交建议

```text
fix(v7.5.2): complete R6 strict acceptance and evidence gates
```

记录：

```bash
git rev-parse HEAD
```

将完整 SHA 记为 `C1_SHA`。

### 冻结规则

- 从此刻开始，不得再修改任何生产代码、测试、Prompt、验收脚本、manifest 逻辑。
- 若真实模型运行暴露需要代码修复的问题：
  1. 宣布当前 C1 和已有运行全部失效；
  2. 修改代码；
  3. 重新执行 R6-04 全部门禁；
  4. 生成新的 C1；
  5. 从 Run A 重新开始。

不得只重跑失败的第二轮并保留第一轮旧证据。

---

## R6-06：同一 C1 SHA 上连续两轮真实 LLM 验收

### 环境

密钥只能通过环境变量提供：

```powershell
$env:REAL_LLM_API_KEY = "<仅当前 shell>"
$env:REAL_LLM_BASE_URL = "https://<provider-host>/v1"
$env:REAL_LLM_MODEL = "<model>"
```

运行前确认：

```bash
git status --short
git rev-parse HEAD
```

必须满足：

- 工作区无代码修改；
- HEAD 等于 `C1_SHA`。

### Run A

```powershell
python scripts/verify_real_llm_acceptance.py `
  --provider openai-compatible `
  --artifact-root artifacts/verification/real-llm `
  --run-id r6-c1-a
```

随后：

```powershell
python scripts/verify_real_llm_evidence.py `
  --artifact-dir artifacts/verification/real-llm/r6-c1-a `
  --expected-sha $env:C1_SHA
```

### Run B

不修改任何代码，再运行：

```powershell
python scripts/verify_real_llm_acceptance.py `
  --provider openai-compatible `
  --artifact-root artifacts/verification/real-llm `
  --run-id r6-c1-b
```

随后执行同样的 evidence verifier。

### 每轮成功条件

- exit code 0；
- `tested_code_sha == C1_SHA`；
- scenario_count=6，passed=6，failed=0；
- audited_agent_run_count=5；
- fallback_count=0；
- mock_count=0；
- degraded_count=0；
- meta_missing_count=0；
- all_meta_observed=true；
- secret scan passed；
- manifest 校验通过。

### 场景专项条件

#### REAL-02

- 最终知识点不少于 2 条；
- 每条有合法来源；
- 若执行 repair：`repair_attempted=true`、`repair_success=true`、`llm_call_count=2`；
- repair 结果原文证据可验证。

#### REAL-03

- 资料内 CRC 问答包含有效 citations，且 material identity 正确；
- 资料外 BGP 问题：`not_found=true`、citations 为空、明确资料不足、无附加无证据技术正文。

#### REAL-04

- 测验题具有 source evidence；
- 提交错误答案后创建 weak point。

#### REAL-05

- 所有任务属于当前课程；
- 至少一个 `task_type=learn`、`target_type=material` 的任务绑定 fixture material；
- 只有 quiz/review 任务时必须失败；
- deadline 与请求一致。

#### REAL-06

- study guide 使用 fixture 中的真实术语；
- evidence IDs 非空。

### 密钥清理

两轮完成后：

```powershell
Remove-Item Env:REAL_LLM_API_KEY
```

如 secret scan 命中真实 key，立即停止；不得提交 artifact，并建议用户轮换该 key。

---

## R6-07：仓库内可复核的脱敏证据包

### 目标

让审计者仅依赖仓库文件即可确认“两轮运行存在、绑定同一 SHA、结果和计数一致”，而不是只看到状态文档中的 run ID。

### 提交目录

从每轮本地 artifact 中复制安全、紧凑的证据文件到：

```text
docs/engineering/evidence/r6/r6-c1-a/
docs/engineering/evidence/r6/r6-c1-b/
```

每个目录只提交：

```text
real-llm-acceptance.json
scenario-results.json
redacted-agent-runs.json
environment-fingerprint.json
request-summary.json
evidence-manifest.json
```

不得提交：

- 原始日志；
- API key；
- Authorization header；
- provider 原始响应；
- 普通用户数据库、上传资料或解析目录。

### 仓库证据校验

校验器必须同时支持 committed compact bundle，或增加单独命令：

```bash
python scripts/verify_real_llm_evidence.py \
  --artifact-dir docs/engineering/evidence/r6/r6-c1-a \
  --expected-sha <C1_SHA> \
  --compact
```

对 A、B 两个目录都运行，并增加一个状态契约测试，确认：

- 两个 run ID 不同；
- tested SHA 完全相同；
- 两轮均 6/6；
- 所有严格计数为 0；
- manifest 哈希可复算；
- 状态文件引用的 run ID 和 evidence 路径真实存在。

---

## R6-08：证据提交 C2

### 目标

C2 只记录 C1 的验证结果，不改变被验证代码。

### C2 允许修改

仅允许：

- `docs/engineering/v7-execution-state.json`
- `docs/engineering/real-llm-acceptance.md`
- 本执行计划或简短执行记录
- `docs/engineering/evidence/r6/**`
- 只用于验证状态/证据文件一致性的状态契约测试（若测试本身在 C1 已提前完成，C2 不应再修改）

最稳妥的方式是：所有证据校验测试和脚本在 C1 完成；C2 只增加证据 JSON 并更新状态/文档。

### C2 禁止修改

- `backend/app/**` 生产代码；
- `frontend/**`；
- `scripts/verify_real_llm_acceptance.py`；
- `scripts/verify_real_llm_evidence.py`；
- Prompt；
- 普通功能测试；
- CI 工作流。

### C2 前校验

```bash
git diff --name-only <C1_SHA>..HEAD
```

必须全部位于允许的 evidence/docs 路径。

重新运行：

```bash
python scripts/verify_real_llm_evidence.py --artifact-dir docs/engineering/evidence/r6/r6-c1-a --expected-sha <C1_SHA> --compact
python scripts/verify_real_llm_evidence.py --artifact-dir docs/engineering/evidence/r6/r6-c1-b --expected-sha <C1_SHA> --compact
python -m pytest backend/app/tests/test_v7_5_2_execution_state.py -q
```

### 状态语义

C2 完成且所有本地门禁通过后，状态可改为：

```json
{
  "overall_status": "verified_locally",
  "local_closure": "V7.5.2_R6_VERIFIED_LOCALLY",
  "release_candidate": null,
  "remote_ci": "pending",
  "real_llm": "success",
  "audit_blockers": ["remote_ci_verification"]
}
```

注意：`verified_locally` 不等于 release candidate。必须同步修改状态契约测试，确保：

- `verified_locally` 时 `release_candidate` 仍为 null；
- 远程 CI 未通过时不得标记最终 verified；
- `done` 任务的 `remaining` 必须为空；
- 证据路径、run ID、C1 SHA 必须真实存在并可验证。

### C2 提交建议

```text
chore(release): record R6 same-SHA real-LLM evidence
```

---

## R6-09：远程 CI 与 PR 收口

### 推送与 CI

1. 推送 C1、C2 到 PR #11 分支。
2. 等待 `.github/workflows/ci.yml` 的以下 jobs 全部成功：
   - Backend Tests；
   - Frontend Unit Tests；
   - Migration Check；
   - E2E Tests；
   - Acceptance Verification。
3. 下载或检查 CI artifacts，确认不是仅 UI 绿色而实际结果文件缺失。
4. CI 执行的是 C2，但必须通过路径白名单证明 C2 相对 C1 不含被验证代码修改。

### PR 描述更新

将 PR #11 描述更新为精确事实，至少列出：

- C1 SHA；
- C2 SHA；
- backend passed 数量、skipped=0；
- frontend unit/type-check/build 结果；
- Playwright passed 数量、failed=0、skipped=0；
- V7 acceptance check 数量与 all_passed；
- Run A、Run B 的 run ID；
- 两轮相同 tested SHA；
- 两轮 6/6、严格计数为 0；
- committed evidence 目录；
- CI workflow run 状态。

### Draft 状态

只有在远程 CI 全部成功且无开放审计 blocker 时，才可将 PR 从 Draft 标记为 Ready for review。

即使满足上述条件，也不得自动合并或创建 tag；等待用户明确决定。

---

# 5. 提交事务与证据关系

最终必须能够得到以下关系：

```text
main/base
   |
   +-- ... R6 development commits
   |
   +-- C1 代码冻结提交
   |      |
   |      +-- Run A artifact: tested_code_sha = C1
   |      +-- Run B artifact: tested_code_sha = C1
   |
   +-- C2 证据提交
          |
          +-- 只含 docs/state/evidence
          +-- 引用 Run A、Run B
          +-- 可重新计算 manifest
```

必须自动或人工验证：

```text
diff(C1, C2) 不包含生产代码、Prompt、验收脚本和普通测试逻辑
```

任何 C2 中的代码变更都会使 Run A、Run B 失去发布证明能力。

---

# 6. 状态文件任务建议

将 `docs/engineering/v7-execution-state.json` 中任务更新为以下逻辑：

```text
AUDIT-R6-01 strict_metadata_chain
AUDIT-R6-02 generic_outline_repair_evidence
AUDIT-R6-03 reproducible_evidence_manifest
AUDIT-R6-04 full_local_regression
AUDIT-R6-05 code_freeze_c1
AUDIT-R6-06 same_sha_real_llm_two_runs
AUDIT-R6-07 committed_evidence_bundle
AUDIT-R6-08 evidence_only_c2
AUDIT-R6-09 remote_ci
```

状态要求：

- 未开始：`pending`；
- 正在执行：`in_progress`；
- 有部分实现但门禁未跑：`partial`；
- 完成：`done`，且 `remaining=[]`、`tests_run` 非空、`commits` 非空或明确为 evidence-only；
- 失败任务不得标记 done；
- 当前任务必须与 `current_task` 一致。

---

# 7. 最终验收清单

只有全部打勾，才能将 PR 标记 Ready for review：

## 代码与契约

- [ ] 验收脚本不推导 `meta_observed`。
- [ ] 验收脚本不把 `fallback_used=None` 转为 false。
- [ ] 所有真实 AgentRun 显式持久化实际 provider/model/fallback/meta。
- [ ] outline repair Prompt 课程通用。
- [ ] repair point 至少一个可逐字核验的 source evidence。
- [ ] 无证据或无关 evidence 的 repair point 被拒绝。
- [ ] REAL-03、REAL-05 严格契约通过。

## 标准门禁

- [ ] Backend 全量 passed，failed=0，skipped=0。
- [ ] Frontend type-check passed。
- [ ] Frontend unit passed，skipped=0。
- [ ] Frontend build passed。
- [ ] Migration dry-run passed。
- [ ] Migration smoke passed。
- [ ] Playwright unexpected=0，skipped=0。
- [ ] V7 acceptance all_passed=true。

## 真实模型

- [ ] C1 已冻结。
- [ ] Run A tested SHA 等于 C1。
- [ ] Run B tested SHA 等于 C1。
- [ ] A、B 均 6/6。
- [ ] A、B audited AgentRun 均为 5。
- [ ] A、B mock/fallback/degraded/meta-missing 均为 0。
- [ ] A、B secret scan passed。
- [ ] A、B manifest 校验通过。

## 证据与 Git

- [ ] committed compact evidence A 存在并可验证。
- [ ] committed compact evidence B 存在并可验证。
- [ ] C2 相对 C1 只有 docs/state/evidence。
- [ ] `git diff --check` 通过。
- [ ] PR #11 远程 CI 全部成功。
- [ ] PR 描述中的数字和 SHA 与 artifact 一致。
- [ ] 未合并、未打 tag，等待用户授权。

---

# 8. 强制停止条件

出现下列任一情况，Agent 必须停止收口、保持 `in_progress` 并报告具体证据：

1. 无法确认当前分支或仓库根目录。
2. 工作区有无法归因的用户修改。
3. 任一完整门禁失败或出现 skipped。
4. 真实运行回退到 mock/system fallback。
5. `meta_observed`、`fallback_used` 等关键字段缺失。
6. Run A、Run B 的 tested SHA 不一致。
7. C1 后发生任何代码或验收逻辑变更。
8. secret scan 命中。
9. evidence manifest 无法复算或文件被篡改。
10. C2 包含生产代码、Prompt、验收脚本或普通测试逻辑。
11. 远程 CI 失败、取消、未运行或结果 artifact 缺失。

不得用“局部通过”“大部分通过”“本机可能有环境问题”等表述替代明确失败状态。

---

# 9. Agent 最终回报格式

Agent 完成后必须输出一份精确执行摘要，至少包含：

```text
Branch:
PR:
C1 SHA:
C2 SHA:
Files changed before C1:
Files changed in C2:
Backend: X passed, 0 failed, 0 skipped
Frontend unit: X passed, 0 failed, 0 skipped
Type-check: passed/failed
Build: passed/failed
Migration dry-run: passed/failed
Migration smoke: passed/failed
Playwright: X passed, 0 failed, 0 skipped
V7 acceptance: X/X passed
Run A ID:
Run A tested SHA:
Run A scenarios:
Run A strict counts:
Run A manifest path/hash:
Run B ID:
Run B tested SHA:
Run B scenarios:
Run B strict counts:
Run B manifest path/hash:
C1..C2 changed-file whitelist: passed/failed
Remote CI run/status:
PR draft/ready state:
Remaining blockers:
```

所有数字、SHA 和路径都必须来自实际执行结果，不得使用计划值或预期值填充。
