# 开发启动与热更新说明

本文档说明如何启动课程学习助手开发环境，以及各类改动在当前运行状态下是否需要重启。

## 一键启动

在项目根目录执行：

```powershell
.\scripts\run_dev.ps1
```

脚本会自动完成以下检查与初始化：

1. 检查 Python、Node.js、npm 是否安装，缺失则停止并提示安装命令。
2. `backend/.venv` 不存在时自动创建，并执行 `pip install -r requirements.txt`。
3. 运行 `scripts/init_db.py` 初始化数据库表结构。
4. `frontend/node_modules` 不存在时自动执行 `npm install`。
5. 在两个新 PowerShell 窗口中分别启动后端（Uvicorn `--reload`）和前端（Vite）。
6. 打印访问地址与 demo 账号；按任意键关闭前后端进程并退出。

### 执行策略提示

若 PowerShell 执行策略阻止脚本运行，在当前会话临时放行即可（仅对当前进程生效，不会修改系统设置）：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

### 访问地址

- 后端 API 文档：http://localhost:8000/docs
- 前端页面：http://localhost:5173
- Demo 账号：`demo / demo123456`

## 编码说明

`scripts/run_dev.ps1` 的所有输出字符串均为 ASCII，避免在中文 Windows + PowerShell 5.1 环境下因非 BOM 文件中的多字节字符被误读而出现 `TerminatorExpectedAtEndOfString` 解析错误。

## 热更新与重启场景

| 修改类型 | 当前运行状态下是否生效 | 处理方式 |
| --- | --- | --- |
| 后端 Python 业务代码 | 通常会自动生效 | `uvicorn --reload` 会检测变更并重启；若无反应，手动重启后端。 |
| 前端 Vue/TS 代码 | 通常会热更新 | Vite 会热更新；若界面未变，刷新浏览器。 |
| `scripts/run_dev.ps1` | 不会影响已启动窗口 | 只影响下一次运行脚本。 |
| `backend/.env` | 不建议依赖热更新 | 修改后重启后端。 |
| `requirements.txt` | 不会自动安装 | 重新 `pip install -r requirements.txt`，再重启后端。 |
| `frontend/package.json` | 不会自动安装 | 重新 `npm install`，再重启前端。 |
| 数据库结构 / 旧库兼容 | 不会自动迁移 | 执行 `python scripts/init_db.py` 或按文档重建开发库。 |

## 手动启动（可选）

如需分别手动启动前后端：

```powershell
# 后端
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 前端
cd frontend
npm run dev
```

## LLM 配置测试说明

个人中心「LLM 配置列表」的「测试」按钮会对配置的 Base URL 发起一次低层 HTTP 探测（`POST {base_url}/chat/completions`），只验证：

- 服务可达、API Key 鉴权通过、模型名被接受；
- 响应是 OpenAI Chat Completions 格式（包含 `choices[0].message.content`）。

测试连接**不要求**模型回复正文是 JSON，因此即使模型返回普通文本 `OK` 也会判定为连接成功。测试失败时会以弹窗展示后端返回的可诊断错误（HTTP 状态码、响应片段、非 JSON / 缺少 choices 等分类原因）。

## 旧资料时间修正

在 timezone-aware UTC 迁移（commit 2c60dfa）之前，`materials.uploaded_at` 以 naive `datetime.utcnow()` 写入，SQLite 不保存时区信息，前端可能显示偏移 8 小时的时间。

如发现旧资料的上传时间仍有偏移，运行以下脚本修正：

```powershell
# Dry-run（只打印，不写入）
python scripts/fix_legacy_material_time.py

# 实际写入
python scripts/fix_legacy_material_time.py --apply
```

脚本会检测 `uploaded_at` 缺少时区信息的行，将其重新标记为 UTC+00:00。新数据已使用 timezone-aware 方案，无需运行此脚本。
