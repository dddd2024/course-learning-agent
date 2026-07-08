# CI 工程证据

本文件归档跨课程知识图谱 v3 收尾阶段的 GitHub Actions CI 证据，作为工程交付闭环的一部分。

## 基线 CI 运行

| 项目 | 值 |
|------|----|
| Workflow | CI |
| Run ID | 28914666690 |
| 触发方式 | push |
| 分支 | main |
| Head SHA | 819da49f59633c631f45e0f117df638ff55b2cc8 |
| 触发提交 | chore(graph): add v2 audit remediation acceptance checks |
| 开始时间 | 2026-07-08 03:10:52 UTC |
| 结束时间 | 2026-07-08 03:16:07 UTC |
| 总耗时 | 约 5m15s |
| 结论 | success |

查看链接: https://github.com/dddd2024/course-learning-agent/actions/runs/28914666690

## Jobs

| Job | 结论 | 耗时 |
|-----|------|------|
| Backend Tests | success | 2m24s |
| Frontend Build | success | 19s |
| Acceptance Script | success | 2m44s |

三个 job 顺序为：Backend Tests 与 Frontend Build 并行；Acceptance Script 依赖前两者完成后运行。

## Artifacts

每个 job 均通过 `actions/upload-artifact@v4` 上传结果（`if: always()`），即使失败也保留证据。

| Artifact 名 | 来源 job | 内容 |
|-------------|----------|------|
| backend-test-result | Backend Tests | `pytest app/tests/ -v` 完整输出（271 passed） |
| frontend-build-result | Frontend Build | `npm run build` 输出 |
| acceptance-result | Acceptance Script | `verify_phase2_engineering.sh` 输出（ACCEPTANCE PASSED） |

## 已知备注

- **Node.js 20 deprecation warning**：`actions/checkout@v4`、`actions/setup-node@v4`、`actions/setup-python@v5`、`actions/upload-artifact@v4` 目标 Node.js 20，被强制运行于 Node.js 24。当前不影响 CI 通过，列为后续依赖升级项。
- CI workflow 已配置 `workflow_dispatch` 触发器，可手动重跑。

## 验证命令

本地复验 CI 证据：

```bash
gh run view 28914666690 --json status,conclusion,jobs
gh api repos/dddd2024/course-learning-agent/actions/runs/28914666690/artifacts \
  --jq '.artifacts[] | {name, size: .size_in_bytes}'
```
