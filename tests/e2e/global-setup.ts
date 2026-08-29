import { chromium, FullConfig } from '@playwright/test'

export default async function globalSetup(config: FullConfig) {
  const browser = await chromium.launch()
  const page = await browser.newPage()

  // 登录
  await page.goto('http://localhost:5173/login')
  await page.fill('input[placeholder="用户名"]', process.env.DC_TEST_USER || 'suiqi')
  await page.fill('input[placeholder="密码"]', process.env.DC_TEST_PASS || 'sui1124')
  await page.click('button:has-text("登录")')
  await page.waitForURL('**/chat', { timeout: 15000 })

  // 保存登录态
  await page.context().storageState({ path: 'tests/e2e/storage-state.json' })
  await browser.close()
  console.log('[global-setup] 登录成功，已保存 storageState')
}
