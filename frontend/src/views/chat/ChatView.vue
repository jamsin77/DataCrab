<template>
  <div class="chat-container">
    <!-- 会话列表侧边栏 -->
    <div class="session-sidebar">
      <el-button class="new-session-btn" @click="handleNewSession">
        <el-icon><Plus /></el-icon> 新建会话
      </el-button>
      <div class="session-list">
        <div
          v-for="session in chatStore.sessions"
          :key="session.id"
          class="session-item"
          :class="{ active: session.id === chatStore.currentSessionId }"
          @click="chatStore.switchSession(session.id)"
        >
          <el-icon><ChatDotRound /></el-icon>
          <span class="session-title">{{ session.title || '新会话' }}</span>
          <el-dropdown trigger="click" @command="(cmd: string) => handleSessionCommand(cmd, session.id)">
            <el-icon class="session-more" @click.stop><MoreFilled /></el-icon>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="rename">重命名</el-dropdown-item>
                <el-dropdown-item command="export">导出对话</el-dropdown-item>
                <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
    </div>

    <!-- 对话主区域 -->
    <div class="chat-main">
      <div v-if="!chatStore.currentSessionId" class="empty-chat">
        <el-icon :size="64" color="#ccc"><ChatDotRound /></el-icon>
        <h2>开始新对话</h2>
        <p>输入自然语言描述，AI将帮你处理数据</p>
      </div>
      <template v-else>
        <!-- 顶部工具栏 -->
        <div class="chat-toolbar">
          <span class="chat-toolbar-title">{{ currentSessionTitle || '新会话' }}</span>
          <div class="chat-toolbar-actions">
            <el-button
              class="export-btn"
              size="small"
              :icon="Download"
              :disabled="chatStore.messages.length === 0"
              @click="handleExportCurrent"
            >
              导出对话
            </el-button>
            <el-button
              class="clear-history-btn"
              size="small"
              :icon="Delete"
              :disabled="chatStore.isStreaming || chatStore.messages.length === 0"
              @click="handleClearMessages"
            >
              清空记录
            </el-button>
          </div>
        </div>
        <!-- 消息流 -->
        <div class="message-list" ref="messageListRef">
          <div
            v-for="msg in chatStore.messages"
            :key="msg.id"
            class="message-item"
            :class="msg.role"
          >
            <div class="message-avatar">
              <el-avatar :size="36" v-if="msg.role === 'assistant'" style="background:#409eff">{{ agentName }}</el-avatar>
              <el-avatar :size="36" v-else>我</el-avatar>
            </div>
            <div class="message-content">
              <!-- 推理过程 -->
              <div v-if="msg.role === 'assistant' && msg.reasoning" class="reasoning-section">
                <div class="reasoning-header" @click="toggleReasoning(msg.id)">
                  <el-icon><CaretRight /></el-icon>
                  <span>推理过程</span>
                  <el-tag v-if="msg.model" size="small" type="info">{{ msg.model }}</el-tag>
                </div>
                <el-collapse-transition>
                  <div v-show="reasoningExpanded[msg.id]" class="reasoning-content">
                    <div class="reasoning-text" v-html="renderMarkdown(msg.reasoning)"></div>
                  </div>
                </el-collapse-transition>
              </div>
              
              <!-- 主要内容 -->
              <div v-if="msg.role === 'assistant' && msg.content" class="markdown-content" v-html="renderMarkdown(msg.content)"></div>
              <div v-else-if="msg.role === 'assistant' && chatStore.isStreaming && !msg.executingMsg && !msg.inspectionReport" class="typing-indicator">
                <span></span><span></span><span></span>
              </div>
              <!-- 数据检查报告 -->
              <div v-if="msg.role === 'assistant' && msg.inspectionReport" class="inspection-report-section">
                <el-collapse model-value="report">
                  <el-collapse-item name="report">
                    <template #title>
                      <el-icon style="margin-right: 4px;"><CircleCheck /></el-icon>
                      <span class="collapse-label">数据检查报告</span>
                    </template>
                    <div class="markdown-content" v-html="renderMarkdown(msg.inspectionReport)"></div>
                  </el-collapse-item>
                </el-collapse>
              </div>
              <!-- 执行进度 -->
              <div v-if="msg.role === 'assistant' && msg.executingMsg" class="executing-indicator">
                <el-icon class="is-loading"><Loading /></el-icon>
                <span>{{ msg.executingMsg }}</span>
              </div>
              <div v-if="msg.role === 'user'" class="user-text">{{ msg.content }}</div>
              
              <div class="msg-time" v-if="msg.created_at">{{ formatMsgTime(msg.created_at) }}</div>
              <div class="message-actions">
                <el-button
                  class="copy-btn"
                  :icon="CopyDocument"
                  circle
                  size="small"
                  @click="handleCopy(msg.content)"
                  title="复制"
                />
              </div>
            </div>
          </div>
        </div>

        <!-- 输入区域 -->
        <div class="input-area">
          <el-input
            v-model="inputText"
            type="textarea"
            :rows="2"
            :autosize="{ minRows: 1, maxRows: 6 }"
            :disabled="chatStore.isStreaming"
            placeholder="输入消息... (Enter发送, Shift+Enter换行, ↑↓浏览历史)"
            @keydown="handleKeyDown"
          />
          <div class="input-actions">
            <el-button
              v-if="chatStore.isStreaming"
              type="danger"
              circle
              @click="chatStore.stopGeneration()"
            >
              <el-icon><VideoPause /></el-icon>
            </el-button>
            <el-button
              v-else
              type="primary"
              circle
              :disabled="!inputText.trim()"
              @click="handleSend"
            >
              <el-icon><Promotion /></el-icon>
            </el-button>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useChatStore } from '@/stores/chat'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CopyDocument, Delete, Download, Loading, CircleCheck } from '@element-plus/icons-vue'
import MarkdownIt from 'markdown-it'
import api from '@/api/index'

const chatStore = useChatStore()
const inputText = ref('')
const messageListRef = ref<HTMLElement>()
const reasoningExpanded = ref<Record<string, boolean>>({})
const agentName = ref('DC')

// 输入历史（↑↓ 浏览）
const inputHistory = ref<string[]>(
  (() => { try { return JSON.parse(localStorage.getItem('dc_chat_history') || '[]') } catch { return [] } })()
)
const historyIdx = ref(-1)
const savedDraft = ref('')

const currentSessionTitle = computed(() => {
  const s = chatStore.sessions.find((s) => s.id === chatStore.currentSessionId)
  return s?.title || ''
})

const md = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
  typographer: true,
})

function renderMarkdown(content: string): string {
  return md.render(content)
}

function formatMsgTime(ts: string): string {
  try {
    const d = new Date(ts.endsWith('Z') ? ts : ts + 'Z')
    return d.toLocaleString('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      hour12: false,
    })
  } catch { return '' }
}

function toggleReasoning(msgId: string) {
  reasoningExpanded.value[msgId] = !reasoningExpanded.value[msgId]
}

async function handleCopy(content: string) {
  try {
    await navigator.clipboard.writeText(content)
    ElMessage.success('已复制到剪贴板')
  } catch {
    const textarea = document.createElement('textarea')
    textarea.value = content
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
    ElMessage.success('已复制到剪贴板')
  }
}

function scrollToBottom(smooth = true) {
  nextTick(() => {
    if (messageListRef.value) {
      messageListRef.value.scrollTo({
        top: messageListRef.value.scrollHeight,
        behavior: smooth ? 'smooth' : 'auto'
      })
    }
  })
}

async function loadAgentConfig() {
  try {
    const config = await api.get('/chat/agent/config')
    if (config && config.short_name) {
      agentName.value = config.short_name
    }
  } catch (e) {
    // 使用默认值
  }
}

onMounted(async () => {
  try {
    await Promise.all([
      chatStore.fetchSessions(),
      loadAgentConfig()
    ])

    // 如果有会话，自动选中第一个并滚动到底部
    if (chatStore.sessions.length > 0 && !chatStore.currentSessionId) {
      await chatStore.switchSession(chatStore.sessions[0].id)
    }
  } catch {
    // 后端可能正在 reload（开发模式改代码触发 uvicorn 重启），静默处理
  }

  // 初始化时滚动到底部
  scrollToBottom(false)
})

// 监听消息变化，自动滚动到底部
watch(
  () => chatStore.messages.length,
  () => {
    scrollToBottom()
  }
)

// 监听流式内容变化，实时滚动
watch(
  () => [chatStore.streamingContent, chatStore.streamingReasoning],
  () => {
    // 推理过程默认折叠
    const lastMsg = chatStore.messages[chatStore.messages.length - 1]
    if (lastMsg && lastMsg.role === 'assistant' && lastMsg.reasoning && reasoningExpanded.value[lastMsg.id] === undefined) {
      reasoningExpanded.value[lastMsg.id] = false
    }
    // 流式更新使用即时滚动，避免 smooth 动画被高频 token 打断
    scrollToBottom(false)
  }
)

// 监听会话切换，滚动到底部
watch(
  () => chatStore.currentSessionId,
  () => {
    nextTick(() => {
      scrollToBottom(false)
    })
  }
)

async function handleNewSession() {
  await chatStore.createSession()
  reasoningExpanded.value = {}
}

async function handleSend() {
  if (chatStore.isStreaming) return
  if (!inputText.value.trim()) return
  const text = inputText.value
  // 保存到输入历史
  inputHistory.value.push(text)
  if (inputHistory.value.length > 50) inputHistory.value = inputHistory.value.slice(-50)
  try { localStorage.setItem('dc_chat_history', JSON.stringify(inputHistory.value)) } catch {}
  historyIdx.value = -1
  inputText.value = ''
  await chatStore.sendMessage(text)
}

async function handleClearMessages() {
  try {
    await ElMessageBox.confirm(
      '确定清空当前会话的所有消息吗？此操作不可恢复。',
      '清空记录',
      { type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  await chatStore.clearMessages()
  reasoningExpanded.value = {}
  ElMessage.success('已清空当前会话记录')
}

function handleKeyDown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  } else if (e.key === 'ArrowUp') {
    if (inputHistory.value.length === 0) return
    e.preventDefault()
    if (historyIdx.value === -1) {
      savedDraft.value = inputText.value
      historyIdx.value = inputHistory.value.length - 1
    } else if (historyIdx.value > 0) {
      historyIdx.value--
    }
    inputText.value = inputHistory.value[historyIdx.value]
  } else if (e.key === 'ArrowDown') {
    if (historyIdx.value === -1) return
    e.preventDefault()
    if (historyIdx.value < inputHistory.value.length - 1) {
      historyIdx.value++
      inputText.value = inputHistory.value[historyIdx.value]
    } else {
      historyIdx.value = -1
      inputText.value = savedDraft.value
    }
  }
}

async function handleSessionCommand(command: string, sessionId: string) {
  if (command === 'delete') {
    await ElMessageBox.confirm('确定删除此会话？', '提示', { type: 'warning' })
    await chatStore.deleteSession(sessionId)
  } else if (command === 'rename') {
    const { value } = await ElMessageBox.prompt('请输入新名称', '重命名')
    if (value) {
      const { chatApi } = await import('@/api/chat')
      await chatApi.updateSession(sessionId, value)
      await chatStore.fetchSessions()
    }
  } else if (command === 'export') {
    await exportSession(sessionId)
  }
}

function formatExportTime(ts: string): string {
  try {
    const d = new Date(ts.endsWith('Z') ? ts : ts + 'Z')
    return d.toLocaleString('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      hour12: false,
    })
  } catch { return ts }
}

async function exportSession(sessionId: string) {
  const { chatApi } = await import('@/api/chat')
  let msgs: any[]
  if (sessionId === chatStore.currentSessionId) {
    msgs = chatStore.messages
  } else {
    msgs = await chatApi.listMessages(sessionId)
  }
  if (!msgs || msgs.length === 0) {
    ElMessage.warning('该会话没有消息可导出')
    return
  }

  const session = chatStore.sessions.find((s) => s.id === sessionId)
  const sessionTitle = session?.title || '新会话'

  const lines: string[] = []
  lines.push(`# ${sessionTitle}`)
  lines.push('')
  lines.push(`> 导出时间：${formatExportTime(new Date().toISOString())}`)
  lines.push(`> 消息数：${msgs.length}`)
  lines.push('')
  lines.push('---')
  lines.push('')

  for (const msg of msgs) {
    const role = msg.role === 'user' ? '用户' : '助手'
    const time = formatExportTime(msg.created_at)
    lines.push(`## ${role}  ${time}`)
    lines.push('')
    if (msg.model) {
      lines.push(`*模型：${msg.model}*`)
      lines.push('')
    }
    if (msg.reasoning) {
      lines.push('<details><summary>推理过程</summary>')
      lines.push('')
      lines.push(msg.reasoning)
      lines.push('')
      lines.push('</details>')
      lines.push('')
    }
    lines.push(msg.content || '')
    lines.push('')
    lines.push('---')
    lines.push('')
  }

  const content = lines.join('\n')
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  const safeTitle = sessionTitle.replace(/[\\/:*?"<>|]/g, '_')
  a.download = `${safeTitle}_${new Date().toISOString().slice(0, 10)}.md`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
  ElMessage.success(`已导出 ${msgs.length} 条对话`)
}

async function handleExportCurrent() {
  if (!chatStore.currentSessionId) return
  await exportSession(chatStore.currentSessionId)
}
</script>

<style lang="scss" scoped>
.chat-container {
  display: flex;
  height: 100%;
}

.session-sidebar {
  width: 260px;
  background: #f7f7f8;
  border-right: 1px solid #e6e6e6;
  display: flex;
  flex-direction: column;
  font-size: 14px;

  .new-session-btn {
    margin: 12px;
  }

  .session-list {
    flex: 1;
    overflow-y: auto;
  }

  .session-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 16px;
    cursor: pointer;
    border-radius: 8px;
    margin: 2px 8px;
    font-size: 13px;

    &:hover, &.active {
      background: #ececec;
    }

    .session-title {
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .session-more {
      opacity: 0;
    }

    &:hover .session-more {
      opacity: 1;
    }
  }
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #fff;
}

.chat-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 20px;
  border-bottom: 1px solid #f0f0f0;
  background: #fafafa;

  .chat-toolbar-title {
    font-size: 14px;
    font-weight: 500;
    color: #606266;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .chat-toolbar-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
  }

  .clear-history-btn,
  .export-btn {
    flex-shrink: 0;
  }
}

.empty-chat {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #999;

  h2 { margin: 16px 0 8px; color: #666; }
  p { margin: 0; }
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  scroll-behavior: smooth;
  font-size: 13px;
}

.message-item {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;

  .message-content {
    flex: 1;
    min-width: 0;
  }

  .message-actions {
    display: flex;
    gap: 8px;
    align-items: center;
    opacity: 0;
    transition: opacity 0.2s;
    margin-top: 4px;
  }

  .msg-time {
    font-size: 11px;
    color: #999;
    margin-top: 2px;
  }

  &:hover .message-actions {
    opacity: 1;
  }

  .copy-btn {
    transition: opacity 0.2s;
  }

  &.user {
    flex-direction: row-reverse;

    .message-content {
      display: flex;
      flex-direction: column;
      align-items: flex-end;

      .user-text {
        background: #409eff;
        color: #fff;
        padding: 8px 14px;
        border-radius: 12px;
        max-width: 85%;
        width: fit-content;
        word-break: break-word;
        font-size: 13px;
        line-height: 1.5;
      }
    }
  }

  &.assistant {
    .message-content {
      .markdown-content {
        max-width: 92%;
        width: fit-content;
        line-height: 1.6;
        font-size: 13px;

        :deep(pre) {
          background: #ffffff;
          color: #303133;
          border: 1px solid #ebeef5;
          padding: 16px;
          border-radius: 8px;
          overflow-x: auto;
          font-size: 13px;
        }

        :deep(code) {
          background: #f0f0f0;
          padding: 2px 6px;
          border-radius: 4px;
          font-size: 13px;
        }

        :deep(pre code) {
          background: none;
          padding: 0;
        }
      }
    }
  }
}

.reasoning-section {
  margin-bottom: 12px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  overflow: hidden;
  
  .reasoning-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: #f5f7fa;
    cursor: pointer;
    user-select: none;
    font-size: 13px;
    
    &:hover {
      background: #ecf0f5;
    }
    
    .el-icon {
      transition: transform 0.3s;
    }
    
    span {
      font-weight: 500;
      color: #606266;
    }
  }
  
  .reasoning-content {
    padding: 12px;
    background: #fafafa;
    border-top: 1px solid #e4e7ed;
    
    .reasoning-text {
      font-size: 14px;
      line-height: 1.6;
      color: #606266;
      
      :deep(p) {
        margin: 8px 0;
      }
      
      :deep(ul), :deep(ol) {
        padding-left: 20px;
        margin: 8px 0;
      }
      
      :deep(code) {
        background: #f0f0f0;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 13px;
      }
    }
  }
}

.inspection-report-section {
  margin: 8px 0 12px 0;
  max-width: 92%;

  .collapse-label {
    font-weight: 500;
    color: #606266;
    font-size: 13px;
  }

  :deep(.el-collapse) {
    border: 1px solid #e4e7ed;
    border-radius: 8px;
    overflow: hidden;
  }

  :deep(.el-collapse-item__header) {
    padding: 0 12px;
    background: #f5f7fa;
    font-size: 13px;
  }

  :deep(.el-collapse-item__content) {
    padding: 12px;
    background: #fafafa;
    font-size: 13px;
    line-height: 1.6;

    .markdown-content {
      max-width: 100%;
      width: 100%;

      :deep(table) {
        border-collapse: collapse;
        width: 100%;
        font-size: 12px;
      }

      :deep(th), :deep(td) {
        border: 1px solid #dcdfe6;
        padding: 4px 8px;
      }

      :deep(th) {
        background: #f0f0f0;
      }
    }
  }
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 8px 0;

  span {
    width: 8px;
    height: 8px;
    background: #999;
    border-radius: 50%;
    animation: typing 1.4s infinite;

    &:nth-child(2) { animation-delay: 0.2s; }
    &:nth-child(3) { animation-delay: 0.4s; }
  }
}

.executing-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  margin: 4px 0;
  background: #f0f9ff;
  border-radius: 6px;
  color: #409eff;
  font-size: 13px;

  .is-loading {
    animation: rotating 1.5s linear infinite;
  }
}

@keyframes typing {
  0%, 60%, 100% { transform: translateY(0); }
  30% { transform: translateY(-8px); }
}

.input-area {
  padding: 16px 20px;
  border-top: 1px solid #e6e6e6;
  display: flex;
  gap: 12px;
  align-items: flex-end;

    .el-textarea {
        flex: 1;
        font-size: 13px;
    }

  .input-actions {
    display: flex;
    gap: 8px;
  }
}
</style>
