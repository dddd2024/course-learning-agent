import { chromium } from 'playwright'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

const baseURL = process.env.FRONTEND_URL || 'http://127.0.0.1:5173'
const outputDir = resolve(process.cwd(), '..', 'artifacts', 'screenshots', 'new-ui')
await mkdir(outputDir, { recursive: true })

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({
  viewport: { width: 1440, height: 1024 },
  deviceScaleFactor: 1,
  colorScheme: 'light',
  reducedMotion: 'no-preference',
})
const page = await context.newPage()
const consoleErrors = []
page.on('console', message => {
  if (message.type() === 'error') consoleErrors.push(message.text())
})

async function settle() {
  await page.waitForLoadState('domcontentloaded')
  await page.waitForTimeout(900)
}

async function capture(name) {
  await settle()
  await page.screenshot({ path: resolve(outputDir, `${name}.png`), fullPage: false })
}

try {
  await page.goto(`${baseURL}/login`)
  await capture('01-login')

  const activeLoginPane = page.locator('.el-tab-pane:visible')
  await activeLoginPane.getByPlaceholder('请输入用户名').fill('demo')
  await activeLoginPane.getByPlaceholder('请输入密码').fill('demo123456')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL('**/dashboard')
  await capture('02-dashboard')

  await page.goto(`${baseURL}/courses`)
  await settle()
  await capture('03-courses')

  await page.getByRole('button', { name: '新建课程' }).click()
  await capture('03b-new-course')
  await page.getByRole('button', { name: '取消' }).click()

  let coursePath = '/courses/1'
  await page.goto(`${baseURL}${coursePath}`)
  if (new URL(page.url()).pathname === coursePath) {
    await capture('04-course-space')

    await page.goto(`${baseURL}${coursePath}/materials`)
    await capture('05-materials')

    await page.goto(`${baseURL}${coursePath}/outline`)
    await capture('06-outline')

    await page.goto(`${baseURL}${coursePath}/chat`)
    await capture('07-course-chat')
  } else {
    coursePath = ''
  }

  await page.goto(`${baseURL}/knowledge-graph`)
  await capture('08-knowledge-graph')

  await page.goto(`${baseURL}/plans`)
  await capture('09-plans')

  await page.goto(`${baseURL}/todos`)
  await capture('10-todos')

  await page.goto(`${baseURL}/profile`)
  await capture('11-profile')

  await page.goto(`${baseURL}/agent-runs`)
  await capture('12-agent-runs')

  console.log(JSON.stringify({ outputDir, coursePath, consoleErrors }, null, 2))
} finally {
  await browser.close()
}
