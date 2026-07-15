import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const toolPath = 'C:/Users/wjc27/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs'
const { Presentation, PresentationFile } = await import(pathToFileURL(toolPath).href)

const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, '..')
const shots = path.join(root, 'artifacts', 'screenshots', 'new-ui')
const assets = path.join(root, 'artifacts', 'presentation', 'assets')
const output = path.join(root, 'artifacts', 'presentation')
const renderDir = path.join(output, 'rendered')
await fs.mkdir(renderDir, { recursive: true })

const C = {
  ink: '#10232D',
  ink2: '#19343F',
  paper: '#F1EBDD',
  paper2: '#E5DDCB',
  white: '#FBF8EF',
  text: '#16252B',
  muted: '#637174',
  celadon: '#7FAE9D',
  celadon2: '#A8C5B8',
  blue: '#4B7390',
  red: '#A45C50',
  line: '#CFC6B3',
}

const deck = Presentation.create({ slideSize: { width: 1280, height: 720 } })

async function bytes(file) {
  const b = await fs.readFile(file)
  return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength)
}

function shape(slide, x, y, w, h, fill, radius = 'rounded-xl', line = 'none') {
  return slide.shapes.add({
    geometry: radius === 'none' ? 'rect' : 'roundRect',
    position: { left: x, top: y, width: w, height: h },
    fill,
    line: line === 'none' ? { style: 'solid', fill: 'none', width: 0 } : { style: 'solid', fill: line, width: 1 },
    ...(radius === 'none' ? {} : { borderRadius: radius }),
  })
}

function text(slide, value, x, y, w, h, size = 24, color = C.text, options = {}) {
  const box = slide.shapes.add({
    geometry: 'textbox',
    position: { left: x, top: y, width: w, height: h },
    fill: 'none',
    line: { style: 'solid', fill: 'none', width: 0 },
  })
  box.text = value
  box.text.style = {
    fontSize: size,
    color,
    fontFamily: options.display ? 'SimSun' : 'Microsoft YaHei',
    bold: options.bold ?? false,
    alignment: options.align || 'left',
    verticalAlignment: options.valign || 'top',
  }
  return box
}

function rule(slide, x, y, w, color = C.line, h = 1) {
  shape(slide, x, y, w, h, color, 'none')
}

async function image(slide, file, x, y, w, h, fit = 'cover', alt = '') {
  const ext = path.extname(file).toLowerCase()
  const contentType = ext === '.jpg' || ext === '.jpeg' ? 'image/jpeg' : 'image/png'
  return slide.images.add({
    blob: await bytes(file),
    contentType,
    alt,
    fit,
    position: { left: x, top: y, width: w, height: h },
    geometry: 'roundRect',
    borderRadius: 'rounded-xl',
  })
}

function chrome(slide, number, eyebrow) {
  slide.background.fill = C.paper
  shape(slide, 0, 0, 18, 720, C.ink, 'none')
  text(slide, eyebrow, 66, 40, 500, 24, 12, C.blue, { bold: true })
  text(slide, String(number).padStart(2, '0'), 1190, 40, 40, 24, 12, C.muted, { align: 'right' })
  rule(slide, 66, 682, 1164)
  text(slide, '课程学习助手 · 大型程序设计实践', 66, 690, 430, 18, 10, C.muted)
}

function title(slide, value, sub = '') {
  text(slide, value, 66, 76, 1140, 70, 34, C.text, { display: true, bold: true })
  if (sub) text(slide, sub, 68, 148, 1080, 38, 16, C.muted)
}

function pill(slide, label, x, y, color = C.celadon) {
  shape(slide, x, y, 116, 34, color, 'rounded-xl')
  text(slide, label, x, y + 6, 116, 22, 13, C.white, { bold: true, align: 'center' })
}

// 01 Cover
{
  const s = deck.slides.add()
  s.background.fill = C.ink
  await image(s, path.join(assets, 'ink-login-landscape.png'), 0, 0, 1280, 720, 'cover', '水墨山水背景')
  shape(s, 0, 0, 500, 720, C.ink, 'none')
  text(s, '大型程序设计实践', 70, 70, 250, 26, 14, C.celadon2, { bold: true })
  text(s, '课程学习助手', 70, 180, 430, 72, 48, C.white, { display: true, bold: true })
  text(s, '让资料、证据与行动形成可验证的学习闭环', 72, 274, 360, 88, 22, C.paper2)
  rule(s, 72, 408, 120, C.celadon, 3)
  text(s, '沉浸式水墨前端 · 系统设计与成果汇报', 72, 438, 370, 56, 17, C.celadon2)
  text(s, '2026', 72, 628, 120, 24, 13, C.paper2)
}

// 02 Problem
{
  const s = deck.slides.add(); chrome(s, 2, '问题与目标')
  title(s, '课程学习的真正难点，是把资料变成可执行路径', '信息很多并不等于学得清楚；系统要持续回答“现在该做什么、依据是什么”。')
  const steps = [
    ['资料分散', '课件、PDF、网页与笔记缺少统一上下文'],
    ['理解断裂', '检索结果难以沉淀为知识点与关系'],
    ['行动模糊', '计划、待办与测验无法从证据自然生长'],
  ]
  steps.forEach((it, i) => {
    const y = 232 + i * 122
    text(s, `0${i + 1}`, 76, y, 70, 44, 30, i === 2 ? C.red : C.blue, { display: true, bold: true })
    text(s, it[0], 164, y, 210, 36, 24, C.text, { bold: true })
    text(s, it[1], 164, y + 42, 520, 42, 16, C.muted)
    rule(s, 164, y + 96, 520)
  })
  shape(s, 760, 224, 418, 342, C.ink, 'rounded-xl')
  text(s, '设计判断', 804, 266, 260, 26, 14, C.celadon2, { bold: true })
  text(s, '学习助手不应只给答案，\n而要给出可追溯的下一步。', 804, 320, 320, 94, 30, C.white, { display: true, bold: true })
  text(s, '资料 → 证据 → 知识点 → 计划 → 执行 → 审计', 804, 474, 316, 58, 16, C.celadon2)
}

// 03 Capabilities
{
  const s = deck.slides.add(); chrome(s, 3, '需求落地')
  title(s, '系统把学习闭环落在六个可验证能力上')
  const items = [
    ['01', '课程空间', '组织课程、教师、学期与学习上下文'],
    ['02', '资料解析', '上传、版本、状态与可追溯片段'],
    ['03', '证据问答', '基于课程资料回答，证据不足时拒绝臆测'],
    ['04', '知识结构', '提取知识点并建立跨课程关系'],
    ['05', '计划执行', '生成阶段任务、今日待办与测验'],
    ['06', '运行审计', '记录模型、耗时、步骤与回退状态'],
  ]
  items.forEach((it, i) => {
    const x = i < 3 ? 76 : 676
    const y = 202 + (i % 3) * 140
    text(s, it[0], x, y, 56, 30, 18, C.celadon, { bold: true })
    text(s, it[1], x + 76, y - 2, 220, 34, 23, C.text, { bold: true })
    text(s, it[2], x + 76, y + 42, 430, 46, 15, C.muted)
    rule(s, x + 76, y + 108, 430)
  })
}

// 04 Architecture
{
  const s = deck.slides.add(); chrome(s, 4, '系统架构')
  title(s, '一套分层架构把交互、检索与审计清晰拆开')
  const layers = [
    { y: 204, label: '体验层', desc: 'Vue 3 · Element Plus · Pinia · ECharts', fill: C.white, color: C.text },
    { y: 300, label: '接口层', desc: 'FastAPI · JWT · REST API · 路由守卫', fill: '#DCE5DE', color: C.text },
    { y: 396, label: '能力层', desc: '资料解析 · RAG 问答 · 知识点 · 计划 · Agent', fill: C.ink2, color: C.white },
    { y: 492, label: '数据层', desc: 'MySQL · Redis · 向量检索 · 文件存储 · 审计日志', fill: C.ink, color: C.white },
  ]
  layers.forEach((l, i) => {
    shape(s, 108 + i * 22, l.y, 1000 - i * 44, 70, l.fill, 'rounded-xl', i < 2 ? C.line : 'none')
    text(s, l.label, 142 + i * 22, l.y + 20, 120, 26, 17, l.color, { bold: true })
    text(s, l.desc, 310 + i * 22, l.y + 20, 700 - i * 44, 28, 17, l.color)
  })
  text(s, '每层职责独立，既便于测试，也让模型调用与学习结果可以被审计。', 110, 606, 1000, 30, 16, C.muted)
}

// 05 Dashboard
{
  const s = deck.slides.add(); chrome(s, 5, '新版核心界面')
  title(s, '新版仪表盘让“下一步行动”成为视觉中心')
  await image(s, path.join(shots, '02-dashboard.png'), 68, 180, 820, 462, 'cover', '新版课程学习助手仪表盘')
  const notes = [
    ['中央主线', '当前课程、进度与下一步任务保持在第一视线。'],
    ['AI 建议', '基于真实数据给出学习建议，不用名言填充空间。'],
    ['右侧轨迹', '今日计划、学习洞察和 Agent 运行形成连续反馈。'],
  ]
  notes.forEach((n, i) => {
    const y = 208 + i * 132
    text(s, n[0], 936, y, 230, 28, 19, i === 0 ? C.red : C.blue, { bold: true })
    text(s, n[1], 936, y + 40, 244, 66, 15, C.muted)
  })
}

// 06 Course context
{
  const s = deck.slides.add(); chrome(s, 6, '课程与资料')
  title(s, '课程空间把资料、知识点和任务收拢到同一上下文')
  await image(s, path.join(shots, '04-course-space.png'), 68, 188, 670, 376, 'cover', '课程空间界面')
  await image(s, path.join(shots, '05-materials.png'), 782, 188, 430, 242, 'cover', '资料管理界面')
  pill(s, '课程为中心', 782, 466, C.blue)
  text(s, '资料上传后保留解析状态、版本与来源；所有问答、知识点和计划继续沿用同一课程上下文。', 782, 518, 418, 86, 17, C.text)
}

// 07 Evidence QA
{
  const s = deck.slides.add(); chrome(s, 7, '可信问答')
  title(s, '回答必须回到课程证据；不够，就明确说不够')
  await image(s, path.join(shots, '07-course-chat.png'), 70, 184, 735, 414, 'cover', '证据不足问答界面')
  const flow = [
    ['检索', '限定当前课程资料'],
    ['判断', '检查证据是否充分'],
    ['回答', '引用片段或返回证据不足'],
  ]
  flow.forEach((f, i) => {
    const y = 218 + i * 118
    text(s, `0${i + 1}`, 862, y, 44, 30, 17, C.celadon, { bold: true })
    text(s, f[0], 920, y, 120, 28, 20, C.text, { bold: true })
    text(s, f[1], 920, y + 38, 240, 44, 15, C.muted)
    if (i < 2) text(s, '↓', 876, y + 82, 30, 28, 22, C.line, { align: 'center' })
  })
  text(s, '可信比“看起来聪明”更重要。', 862, 580, 300, 32, 18, C.red, { bold: true })
}

// 08 Graph and plan
{
  const s = deck.slides.add(); chrome(s, 8, '知识到行动')
  title(s, '知识图谱和学习计划，把理解继续推向执行')
  await image(s, path.join(shots, '08-knowledge-graph.png'), 68, 188, 560, 315, 'cover', '知识图谱界面')
  await image(s, path.join(shots, '09-plans.png'), 652, 188, 560, 315, 'cover', '学习计划界面')
  text(s, '关系可见', 68, 540, 180, 30, 21, C.blue, { bold: true })
  text(s, '前置、相似、对比和易混关系帮助定位知识结构。', 68, 580, 500, 50, 16, C.muted)
  text(s, '任务可做', 652, 540, 180, 30, 21, C.red, { bold: true })
  text(s, '截止日期、预计时长与完成标准让学习计划可执行。', 652, 580, 500, 50, 16, C.muted)
}

// 09 Visual language
{
  const s = deck.slides.add(); chrome(s, 9, '设计语言')
  title(s, '水墨不是贴图，而是一套贯穿产品的界面语言')
  await image(s, path.join(shots, '01-login.png'), 68, 186, 660, 372, 'cover', '水墨风登录界面')
  const tokens = [
    [C.ink, '深墨', '导航、图谱与学习轨迹'],
    [C.paper, '宣纸', '主工作区与信息层级'],
    [C.celadon, '青瓷', '进度、状态与关键反馈'],
    [C.red, '朱砂', '重点提醒与风险语义'],
  ]
  tokens.forEach((t, i) => {
    const y = 202 + i * 88
    shape(s, 792, y, 42, 42, t[0], 'rounded-xl', t[0] === C.paper ? C.line : 'none')
    text(s, t[1], 856, y - 1, 100, 28, 19, C.text, { bold: true })
    text(s, t[2], 856, y + 32, 270, 28, 14, C.muted)
  })
  text(s, '低速粒子与淡墨连接线只承担氛围，不抢占功能内容。', 792, 584, 360, 42, 15, C.blue)
}

// 10 Challenges
{
  const s = deck.slides.add(); chrome(s, 10, '难点与亮点')
  title(s, '高难点集中在资料解析、证据约束与运行可追溯')
  const rows = [
    ['01', '多格式资料进入统一结构', '把页面、结构块、检索切块和来源位置关联起来，让后续引用能够回到原文。'],
    ['02', '模型回答接受证据边界', '把“证据不足”设计为正式结果，避免系统在缺少原文时生成未经证实的课程结论。'],
    ['03', 'Agent 每一步都可解释', '记录请求模型、实际模型、Fallback、耗时、输入输出摘要与步骤明细。'],
  ]
  rows.forEach((r, i) => {
    const y = 210 + i * 132
    text(s, r[0], 78, y, 60, 38, 26, i === 1 ? C.red : C.blue, { display: true, bold: true })
    text(s, r[1], 166, y, 360, 38, 22, C.text, { bold: true })
    text(s, r[2], 560, y, 610, 72, 16, C.muted)
    rule(s, 166, y + 98, 1004)
  })
}

// 11 Engineering QA
{
  const s = deck.slides.add(); s.background.fill = C.ink
  text(s, '工程化验收', 68, 44, 300, 24, 12, C.celadon2, { bold: true })
  text(s, '每个关键动作都有可重复的验收路径', 68, 86, 1030, 60, 34, C.white, { display: true, bold: true })
  const checks = [
    ['01', '构建', 'vue-tsc + Vite 构建成功'],
    ['02', '测试', '13 个测试文件、41 项前端测试通过'],
    ['03', '视觉', '12 个功能状态截图，控制台 0 错误'],
    ['04', '文档', '实践报告保持 30 页并完成逐页渲染检查'],
  ]
  checks.forEach((c, i) => {
    const x = 72 + i * 296
    text(s, c[0], x, 206, 60, 30, 18, C.celadon, { bold: true })
    text(s, c[1], x, 260, 230, 34, 24, C.white, { bold: true })
    text(s, c[2], x, 312, 238, 88, 16, C.paper2)
    rule(s, x, 424, 230, '#36505B')
  })
  text(s, '设计不是最后贴上去的皮肤；它和构建、测试、截图、报告一起成为可验证交付。', 72, 526, 1040, 54, 22, C.celadon2, { display: true })
  text(s, '课程学习助手 · 大型程序设计实践', 72, 676, 400, 18, 10, '#78909A')
}

// 12 Close
{
  const s = deck.slides.add(); chrome(s, 12, '结论与演示')
  title(s, '课程学习助手已经形成可演示、可验证、可继续扩展的学习闭环')
  const claims = [
    ['体验', '下一步行动清晰，水墨语言统一'],
    ['可信', '回答依赖课程证据，边界明确'],
    ['执行', '知识点、计划、待办与测验相互连接'],
    ['工程', '构建、测试、审计和报告均可复现'],
  ]
  claims.forEach((c, i) => {
    const y = 210 + i * 82
    text(s, c[0], 84, y, 90, 30, 19, i === 1 ? C.red : C.blue, { bold: true })
    text(s, c[1], 202, y, 500, 32, 18, C.text)
    rule(s, 202, y + 48, 500)
  })
  shape(s, 784, 202, 392, 322, C.ink, 'rounded-xl')
  text(s, '现场演示路径', 828, 244, 240, 28, 16, C.celadon2, { bold: true })
  text(s, '登录 → 仪表盘\n→ 课程与资料\n→ 证据问答\n→ 图谱与计划\n→ Agent 运行审计', 828, 306, 280, 174, 24, C.white, { display: true })
  text(s, 'Q & A', 84, 580, 250, 52, 38, C.text, { display: true, bold: true })
}

async function writeBlob(file, blob) {
  await fs.writeFile(file, new Uint8Array(await blob.arrayBuffer()))
}

for (const [i, slide] of deck.slides.items.entries()) {
  const stem = `slide-${String(i + 1).padStart(2, '0')}`
  await writeBlob(path.join(renderDir, `${stem}.png`), await deck.export({ slide, format: 'png', scale: 1 }))
  const layout = await slide.export({ format: 'layout' })
  await fs.writeFile(path.join(renderDir, `${stem}.layout.json`), await layout.text())
}

await writeBlob(path.join(renderDir, 'deck-montage.webp'), await deck.export({ format: 'webp', montage: true, scale: 1 }))
await (await PresentationFile.exportPptx(deck)).save(path.join(output, '课程学习助手_大型程序设计实践汇报.pptx'))
console.log(JSON.stringify({ slides: deck.slides.items.length, output }, null, 2))
