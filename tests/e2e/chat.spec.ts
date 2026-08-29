import { test, expect } from '@playwright/test'
import { testGroups } from './test-cases'
import { switchToSession, sendMessage, waitForResponse, getLastAssistantContent, handleSuggestion } from './helpers'
import * as fs from 'fs'
import { execSync } from 'child_process'

const BACKEND_LOG = 'C:\\Users\\suiqi\\AppData\\Local\\Temp\\opencode\\datacrab\\backend.err.log'
const PROJECT_DIR = 'D:\\DataCrab'

// 测试失败时自动收集信息并调 OpenCode 分析
test.afterEach(async ({}, testInfo) => {
  if (testInfo.status !== 'failed' && testInfo.status !== 'timedOut') return

  console.log(`\n[afterEach] 测试 "${testInfo.title}" 失败，收集信息调 OpenCode 分析...`)

  // 1. 收集后端日志最后 50 行
  let logTail = ''
  try {
    const content = fs.readFileSync(BACKEND_LOG, 'utf-8')
    const lines = content.split('\n')
    logTail = lines.slice(-50).join('\n')
  } catch (e) {
    logTail = '(读取后端日志失败)'
  }

  // 2. 收集错误信息（清洗控制字符）
  const error = (testInfo.error?.message || '未知错误').replace(/[\x00-\x1F\x7F]/g, '')
  const prompt = `DataCrab 的 Playwright 测试用例 "${testInfo.title}" 失败了。错误信息：${error}。后端日志最后50行：${logTail}。请分析失败原因，定位是前端还是后端的问题，只分析不修改，给出修复建议。`

  // 3. 调 OpenCode 分析
  try {
    console.log('[afterEach] 调用 opencode run...')
    const cleanPrompt = prompt.replace(/[\x00-\x1F\x7F]/g, '').replace(/"/g, "'").replace(/\n/g, ' ')
    execSync(`opencode run "${cleanPrompt}"`, {
      cwd: PROJECT_DIR,
      timeout: 300000,
      stdio: 'inherit',
    })
    console.log('[afterEach] opencode 分析完成')
  } catch (e: any) {
    console.log(`[afterEach] opencode 调用失败: ${e.message}`)
    const reportPath = `tests/e2e/failure-${Date.now()}.txt`
    fs.writeFileSync(reportPath, prompt, 'utf-8')
    console.log(`[afterEach] 失败报告已保存到 ${reportPath}`)
  }
})

// globalSetup 负责登录，所有测试复用登录态
test.describe('Chat 数据演进流程测试', () => {
  test('数据演进完整流程', async ({ page }) => {
    // 切换到已有的"数据演进"会话
    await switchToSession(page, '数据演进')

    for (const group of testGroups) {
      for (let i = 0; i < group.steps.length; i++) {
        const step = group.steps[i]
        console.log(`  [step ${i + 1}/${group.steps.length}] 发送: "${step.msg}"`)

        await sendMessage(page, step.msg)
        const result = await waitForResponse(page)
        console.log(`  [step ${i + 1}] 响应结果: ${result}`)

        const content = await getLastAssistantContent(page)
        console.log(`  [step ${i + 1}] assistant 内容: ${content?.slice(0, 120)}`)

        // 处理 suggestion
        if (step.expect.action && step.expect.action !== 'no_suggestion') {
          if (result !== 'suggestion') {
            throw new Error(`步骤 ${i + 1} 期望 suggestion 但得到 ${result}`)
          }
          await handleSuggestion(page, step.expect.action)
          // 等待 suggestion 处理后流式完全结束（避免上一次 generate() db session 未释放就发下一条消息）
          await page.waitForTimeout(2000)
        } else if (result === 'done') {
          if (content.length === 0) {
            throw new Error(`步骤 ${i + 1} Agent 返回空内容`)
          }
        }

        // 步骤间等待页面稳定 + 后端 generate() db session 释放
        await page.waitForTimeout(3000)
      }
    }
  })
})
