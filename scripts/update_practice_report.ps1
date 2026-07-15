param(
    [string]$DocumentPath = "F:\course-learning-agent\artifacts\report\课程学习助手_实践报告_新版.docx",
    [string]$ImageDirectory = "F:\course-learning-agent\artifacts\report\ready-images"
)

$ErrorActionPreference = 'Stop'

$images = @(
    'fig-5-1-login.png',
    'fig-5-2-dashboard.png',
    'fig-5-3-new-course.png',
    'fig-5-4-course-space.png',
    'fig-5-5-materials.png',
    'fig-5-6-outline.png',
    'fig-5-7-knowledge-graph.png',
    'fig-5-8-course-chat.png',
    'fig-5-9-plans.png',
    'fig-5-10-todos.png',
    'fig-5-11-profile.png',
    'fig-5-12-agent-runs.png'
)

$replacements = [ordered]@{
    '系统已形成可运行的前后端应用，并发布 v1.0.0 稳定源代码版本。本节结合实际运行截图说明主要界面和验收结果。截图中的测试账号仅用于本地演示；模型 API Key 均以脱敏形式展示。' = '系统已形成可运行的前后端应用，并完成水墨沉浸式前端改造。本节结合新版真实运行截图说明主要界面和验收结果。截图中的测试账号仅用于本地演示；模型 API Key 均以脱敏形式展示。'
    '登录页面提供登录、注册和记住登录状态入口。后端对密码进行哈希验证，登录成功后签发 JWT；路由守卫在进入业务页面前再次校验当前用户。' = '登录页面以留白、水墨山水和低速粒子构成沉浸式入口，同时保留登录、注册和记住登录状态。后端对密码进行哈希验证，登录成功后签发 JWT；路由守卫在进入业务页面前再次校验当前用户。'
    '仪表盘集中展示课程、资料、计划、待办和近期学习状态，为用户提供跨课程概览和常用功能入口。' = '仪表盘以中央山水学习画布和深色学习轨迹侧栏组织信息，集中展示当前课程、下一步行动、AI 学习建议、今日计划和近期运行记录，为用户提供清晰的学习主线。'
    '用户可填写课程名称、授课教师、学期、课程简介和主题色。课程信息由前端表单校验后写入后端，并自动归属于当前用户。' = '新版纸感弹窗保持课程名称、授课教师、学期、课程简介和主题色等完整字段。课程信息由前端表单校验后写入后端，并自动归属于当前用户。'
    '课程详情页以课程为中心汇总资料、问答、知识点、文档学习、学习计划、测验和知识图谱入口。示例课程已经包含 8 份资料和 57 个知识点。' = '课程空间延续宣纸与墨色视觉语言，以课程为中心汇总资料、问答、知识点、文档学习、学习计划、测验和知识图谱入口；统计值来自当前演示数据。'
    '资料页面支持拖拽或点击上传，限制文件类型和大小，并显示资料类型、状态、版本、图片完整性、上传时间和操作。解析完成的资料可查看片段或重新处理。' = '资料页面在统一的纸感信息层中支持拖拽或点击上传，限制文件类型和大小，并显示资料类型、状态、版本、图片完整性、上传时间和操作。解析完成的资料可查看片段或重新处理。'
    '知识点页面展示标题、摘要、重要度、考查方式、建议任务和来源片段，并允许重新生成。示例课程共形成 57 个知识点。' = '知识点大纲在新版界面中展示标题、摘要、重要度、考查方式、建议任务和来源片段，并允许重新生成；数量与状态均以当前课程数据为准。'
    '知识图谱使用节点颜色区分课程，使用不同线型和关系类型表示相似、对比、前置、易混和上下位等联系，支持课程、关系和状态筛选。' = '知识图谱采用深墨夜色画布承载节点网络，使用颜色和关系类型表示相似、对比、前置、易混和上下位等联系，支持课程、关系和状态筛选。'
    '示例计划根据截止日期和每日 120 分钟可用时间生成 12 个阶段任务。任务记录课程、类型、预计时长、优先级、完成标准、执行状态和验证方式，并可直接进入知识学习或生成测验。' = '学习计划根据截止日期和每日可用时间生成阶段任务。任务记录课程、类型、预计时长、优先级、完成标准、执行状态和验证方式，并可直接进入知识学习或生成测验。'
}

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $doc = $word.Documents.Open($DocumentPath, $false, $false)

    foreach ($entry in $replacements.GetEnumerator()) {
        $range = $doc.Content
        if (-not $range.Find.Execute($entry.Key)) {
            throw "未找到待替换文本：$($entry.Key)"
        }
        $range.Text = $entry.Value
    }

    for ($offset = 0; $offset -lt $images.Count; $offset++) {
        $index = 6 + $offset
        $shape = $doc.InlineShapes.Item($index)
        $width = $shape.Width
        $height = $shape.Height
        $range = $shape.Range.Duplicate
        $shape.Delete()

        $imagePath = Join-Path $ImageDirectory $images[$offset]
        if (-not (Test-Path -LiteralPath $imagePath)) {
            throw "截图不存在：$imagePath"
        }
        $newShape = $doc.InlineShapes.AddPicture($imagePath, $false, $true, $range)
        $newShape.LockAspectRatio = 0
        $newShape.Width = $width
        $newShape.Height = $height
    }

    $doc.Fields.Update() | Out-Null
    $doc.Save()
}
finally {
    if ($doc) { $doc.Close($true) }
    $word.Quit()
    if ($doc) { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($doc) | Out-Null }
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
