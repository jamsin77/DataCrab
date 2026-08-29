import { Page, expect } from '@playwright/test'

const USERNAME = process.env.DC_TEST_USER || 'suiqi'
const PASSWORD = process.env.DC_TEST_PASS || 'sui1124'

/**
 * 登录并保存 storageState
 */
export async function login(page: Page) {
  await page.goto('/login')
  await page.fill('input[placeholder="用户名"]', USERNAME)
  await page.fill('input[placeholder="密码"]', PASSWORD)
  await page.click('button:has-text("登录")')
  await page.waitForURL('**/chat', { timeout: 15000 })
  await page.context().storageState({ path: 'tests/e2e/storage-state.json' })
}

/**
 * 新建会话
 */
export async function createSession(page: Page) {
  await page.click('.new-session-btn')
  await page.waitForTimeout(1000)
}

/**
 * 切换到指定名称的会话（不存在则新建）
 */
export async function switchToSession(page: Page, title: string) {
  await page.goto('/chat')
  await page.waitForTimeout(1000)
  // 查找会话列表中标题匹配的项
  const items = page.locator('.session-list .session-item')
  const count = await items.count()
  for (let i = 0; i < count; i++) {
    const text = await items.nth(i).textContent() || ''
    if (text.includes(title)) {
      await items.nth(i).click()
      await page.waitForTimeout(1500)
      return
    }
  }
  // 没找到则新建
  await createSession(page)
}

/**
 * 在 Chat 输入框输入消息并发送
 */
export async function sendMessage(page: Page, message: string) {
  const textarea = page.locator('.input-area textarea')
  await textarea.fill(message)
  await textarea.press('Enter')
}

/**
 * 等待 SSE 流式响应完成
 * 检测条件：消息列表最后一条 assistant 消息不再变化（或出现 done/suggestion 卡片）
 */
export async function waitForResponse(page: Page, timeout = 180000): Promise<string> {
  // 等待 assistant 消息出现
  await page.waitForSelector('.message-list .message-item.assistant:last-child', { timeout })

  const startTime = Date.now()
  let lastContent = ''
  let stableCount = 0

  while (Date.now() - startTime < timeout) {
    // 1. 检测 suggestion 卡片（等流式稳定后再返回，避免后端 generate() 未结束就发下一条消息导致 DB 锁）
    const suggestion = page.locator('.message-list .message-item.assistant:last-child .suggestion-card')
    if (await suggestion.count() > 0) {
      // 检测是否有正在转圈的图标（流式可能还在进行）
      const spinner = page.locator('.message-list .message-item.assistant:last-child .el-icon.is-loading')
      const hasSpinner = await spinner.count() > 0
      if (!hasSpinner) {
        await page.waitForTimeout(1000)
        return 'suggestion'
      }
    }

    // 2. 检测是否有正在转圈的图标（流式进行中）
    const spinner = page.locator('.message-list .message-item.assistant:last-child .el-icon.is-loading')
    const hasSpinner = await spinner.count() > 0

    // 3. 检测内容是否稳定（连续 3 次相同 = done）
    const content = await page.locator('.message-list .message-item.assistant:last-child .message-content').textContent() || ''
    const execMsgs = await page.locator('.message-list .message-item.assistant:last-child .executing-line').count()

    if (!hasSpinner && content === lastContent && execMsgs === 0) {
      stableCount++
      if (stableCount >= 3) {
        return 'done'
      }
    } else {
      stableCount = 0
    }
    lastContent = content

    await page.waitForTimeout(2000)
  }
  return 'timeout'
}

/**
 * 获取最后一条 assistant 消息内容
 */
export async function getLastAssistantContent(page: Page): Promise<string> {
  return await page.locator('.message-list .message-item.assistant:last-child .message-content').textContent() || ''
}

/**
 * 处理 suggestion 卡片
 */
export async function handleSuggestion(page: Page, action: string) {
  if (action === 'no_suggestion') return

  const card = page.locator('.message-list .message-item.assistant:last-child .suggestion-card')
  if (await card.count() === 0) return

  switch (action) {
    case 'select_data':
      await card.getByRole('button', { name: '选择此数据' }).first().click()
      break
    case 'use_skill':
      await card.getByRole('button', { name: /使用/ }).first().click()
      break
    case 'continue':
      await card.getByRole('button', { name: /继续/ }).first().click()
      break
  }
  await page.waitForTimeout(2000)
}

/**
 * 读取后端日志最后 N 行匹配 classify 结果
 */
export async function readClassifyResult(logPath: string): Promise<string[]> {
  const fs = require('fs')
  const content = fs.readFileSync(logPath, 'utf-8')
  const lines = content.split('\n').filter(l => l.includes('[classify]'))
  return lines.slice(-5)
}
