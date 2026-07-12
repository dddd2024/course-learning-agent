# 资料自动解析与删除功能修复 实施计划

> 来源：`课程学习助手_资料自动解析与删除功能修复计划.docx`
> 仓库：dddd2024/course-learning-agent
> 分支：main

## 背景

资料管理流程存在两个核心问题：
1. **上传后不能自动解析**：上传成功后状态为「已上传」，用户必须逐个点击「解析」才能让资料进入问答/检索/知识点/图谱。
2. **资料不能删除**：资料列表没有删除按钮，API 层也缺少 `deleteMaterial`，无法清理误传、重复或过期资料。

## 目标

1. 前端上传资料成功后自动触发 `parseMaterial(material.id)`，不再要求用户逐个点击「解析」。
2. 资料列表操作列新增「删除」按钮，带二次确认，删除后刷新列表。
3. 前端 API 新增 `deleteMaterial(materialId)`。
4. 后端新增 `DELETE /api/v1/materials/{material_id}`，按 `current_user` 做用户隔离。
5. 删除时清理 `Material`、`MaterialChunk`、`MaterialSecurityFinding` 和 `storage/uploads` 下原始文件。
6. `processing` 状态下禁止删除，返回 400 统一错误。
7. 补充后端测试：删除成功、跨用户 404、chunk 清理、磁盘文件缺失不失败、processing 禁止删除。
8. 关键后端测试加入验收脚本。

## 非目标

- 不引入 Celery/Redis/消息队列。
- 不重写整个 MaterialsView。
- 不改变现有 parse endpoint 的基本契约。
- 不把「片段/chunk/RAG」说明大段展示给普通用户。

## 设计决策

- **DELETE endpoint 位置**：放在 `parse.py`（已挂载在 `/materials` 前缀，且已有 `_get_owned_material` helper），避免在 `materials.py`（挂载在 `/courses` 前缀）引入路径混乱。
- **自动解析**：前端 `customUpload` 上传成功后调用 `parseMaterial(res.data.id)`，复用现有轮询逻辑。上传与解析保持两个独立后端接口，便于失败重试和测试。
- **删除清理范围**：`MaterialChunk`、`MaterialSecurityFinding` 按行删除；`Material` 主记录删除；磁盘文件按 `material.file_path` 删除，缺失静默跳过。
- **processing 保护**：删除前检查 `material.status == 'processing'`，抛 `BusinessException(400)`。

## 任务分解

### Task A：后端 DELETE /materials/{id} + 清理（TDD）

文件：
- 修改：`backend/app/api/v1/endpoints/parse.py`
- 测试：`backend/app/tests/test_materials.py`（新增删除用例）

测试用例（对应 docx TABLE 10）：
1. `test_delete_material_success` — 删除当前用户资料返回 204，列表不再出现。
2. `test_delete_other_user_material_returns_404` — 删除他人资料返回 404。
3. `test_delete_material_clears_chunks` — 删除后 chunks 查询返回 total=0。
4. `test_delete_material_missing_disk_file_still_succeeds` — 磁盘文件缺失仍返回 204。
5. `test_delete_processing_material_returns_400` — processing 状态删除返回 400。

### Task B：前端 deleteMaterial + 删除按钮 + 上传后自动解析

文件：
- 修改：`frontend/src/api/material.ts`（新增 `deleteMaterial`）
- 修改：`frontend/src/views/MaterialsView.vue`：
  - `customUpload` 上传成功后自动调用 `parseMaterial(res.data.id)`。
  - 操作列新增「删除」按钮（危险色 + 二次确认）；processing 状态禁用。
  - 删除成功后刷新列表；若正在查看该资料片段则关闭弹窗。
  - 按钮文案从「解析/重新解析」调整为「处理/重新处理」（贴近用户语言）。

### Task C：关键后端测试加入验收脚本

文件：`scripts/verify_phase2_engineering.ps1`

新增一个 section：运行 5 个删除相关测试，确保回归保护。

## 验收

```powershell
cd backend; python -m pytest app/tests/test_parse.py app/tests/test_materials.py app/tests/test_search.py -q
cd ../frontend; npm run build
cd ..; pwsh .\scripts\verify_phase2_engineering.ps1
```
