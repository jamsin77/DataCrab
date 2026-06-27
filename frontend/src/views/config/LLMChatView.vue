<template>
  <div class="llm-chat-container">
    <div class="llm-chat-main">
      <div class="llm-chat-messages" ref="msgListRef">
        <div v-if="messages.length === 0" class="llm-chat-empty">
          <el-icon :size="48" color="#c0c4cc"><ChatDotRound /></el-icon>
          <p>直接与平台大模型对话</p>
          <p class="sub">支持流式输出、推理过程展示、多轮对话</p>
        </div>
        <div
          v-for="(msg, idx) in messages"
          :key="idx"
          class="llm-msg"
          :class="msg.role"
        >
          <div class="llm-msg-avatar">
            <el-avatar :size="34" v-if="msg.role === 'assistant'" style="background:#409eff">AI</el-avatar>
            <el-avatar :size="34" v-else style="background:#67c23a">我</el-avatar>
          </div>
          <div class="llm-msg-body">
            <div v-if="msg.role === 'user'" class="llm-msg-user">{{ msg.content }}</div>
            <div v-else class="llm-msg-assistant">
              <div v-if="msg.thinking" class="llm-msg-thinking">
                <div class="thinking-header">
                  <el-icon class="thinking-spin"><Loading /></el-icon>
                  <span>推理过程</span>
                </div>
                <div class="thinking-body">{{ msg.thinking }}</div>
              </div>
              <div v-if="msg.content" class="llm-msg-content markdown-body" v-html="renderMarkdown(msg.content)"></div>
            </div>
          </div>
        </div>
        <div v-if="streaming && !messages.length" class="llm-msg assistant">
          <div class="llm-msg-avatar"><el-avatar :size="34" style="background:#409eff">AI</el-avatar></div>
          <div class="llm-msg-body">
            <div class="typing-indicator"><span></span><span></span><span></span></div>
          </div>
        </div>
      </div>

      <div class="llm-chat-toolbar">
        <el-select v-model="mode" size="small" style="width: 130px">
          <el-option label="流式+推理" value="thinking" />
          <el-option label="流式输出" value="stream" />
          <el-option label="非流式" value="sync" />
        </el-select>
        <el-slider v-model="temperature" :min="0" :max="2" :step="0.1" style="width: 120px" size="small" />
        <span class="temp-label">T={{ temperature }}</span>
        <el-button size="small" text type="danger" @click="clearMessages" :disabled="streaming">清空对话</el-button>
      </div>

      <div class="llm-chat-input">
        <el-input
          v-model="input"
          type="textarea"
          :rows="2"
          :autosize="{ minRows: 1, maxRows: 6 }"
          placeholder="输入消息... (Enter发送, Shift+Enter换行)"
          @keydown="handleKeyDown"
          :disabled="streaming"
        />
        <el-button
          v-if="streaming"
          type="danger"
          circle
          @click="stopGeneration"
        >
          <el-icon><VideoPause /></el-icon>
        </el-button>
        <el-button
          v-else
          type="primary"
          circle
          :disabled="!input.trim()"
          @click="sendMessage"
        >
          <el-icon><Promotion /></el-icon>
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { ChatDotRound, Loading, VideoPause, Promotion } from '@element-plus/icons-vue'
import api from '@/api/index'
import { ElMessage } from 'element-plus'
import markdownIt from 'markdown-it'

const md = markdownIt({ html: false, breaks: true, linkify: true })
function renderMarkdown(text: string) {
  return md.render(text || '')
}

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  thinking?: string
}

const messages = ref<ChatMessage[]>([])
const input = ref('')
const streaming = ref(false)
const mode = ref('thinking')
const temperature = ref(0.7)
let abortController: AbortController | null = null
const msgListRef = ref<HTMLElement | null>(null)

function scrollToBottom() {
  nextTick(() => {
    if (msgListRef.value) {
      msgListRef.value.scrollTop = msgListRef.value.scrollHeight
    }
  })
}

function clearMessages() {
  messages.value = []
  input.value = ''
}

function handleKeyDown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}

function stopGeneration() {
  if (abortController) {
    abortController.abort()
  }
}

async function sendMessage() {
  if (!input.value.trim() || streaming.value) return

  const userMsg = input.value.trim()
  messages.value.push({ role: 'user', content: userMsg })
  input.value = ''
  streaming.value = true
  scrollToBottom()

  if (mode.value === 'sync') {
    await sendSync(userMsg)
  } else if (mode.value === 'stream') {
    await sendStream(userMsg)
  } else {
    await sendThinking()
  }
}

async function sendSync(userMsg: string) {
  const assistantIdx = messages.value.length
  messages.value.push({ role: 'assistant', content: '' })

  try {
    const history = messages.value.slice(0, assistantIdx).map(m => ({
      role: m.role, content: m.content
    }))

    const res = await api.post('/llm/chat-messages', {
      messages: history,
      temperature: temperature.value,
    })
    messages.value[assistantIdx].content = res.content || ''
  } catch (e: any) {
    messages.value[assistantIdx].content = `调用失败: ${e.response?.data?.detail || e.message || String(e)}`
  } finally {
    streaming.value = false
    scrollToBottom()
  }
}

async function sendStream(userMsg: string) {
  const assistantIdx = messages.value.length
  messages.value.push({ role: 'assistant', content: '' })
  abortController = new AbortController()

  try {
    const token = localStorage.getItem('access_token')
    const history = messages.value.slice(0, assistantIdx).map(m => ({
      role: m.role, content: m.content
    }))

    const response = await fetch('/api/v1/llm/chat-stream-messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        messages: history,
        temperature: temperature.value,
      }),
      signal: abortController.signal,
    })

    if (!response.ok) {
      const errText = await response.text()
      throw new Error(errText || `HTTP ${response.status}`)
    }

    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed.startsWith('data: ')) continue
        try {
          const data = JSON.parse(trimmed.slice(6))
          if (data.type === 'content') {
            messages.value[assistantIdx].content += data.content
            scrollToBottom()
          } else if (data.type === 'error') {
            messages.value[assistantIdx].content += `\n\n错误: ${data.content}`
          }
        } catch { /* skip */ }
      }
    }
  } catch (e: any) {
    if (e.name === 'AbortError') {
      messages.value[assistantIdx].content += '\n\n*[已停止生成]*'
    } else {
      messages.value[assistantIdx].content = `请求出错: ${e.message || String(e)}`
    }
  } finally {
    streaming.value = false
    abortController = null
    scrollToBottom()
  }
}

async function sendThinking() {
  const assistantIdx = messages.value.length
  messages.value.push({ role: 'assistant', content: '', thinking: '' })
  abortController = new AbortController()

  try {
    const token = localStorage.getItem('access_token')
    const history = messages.value.slice(0, assistantIdx).map(m => ({
      role: m.role, content: m.content
    }))

    const response = await fetch('/api/v1/llm/chat-stream-thinking', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        messages: history,
        temperature: temperature.value,
      }),
      signal: abortController.signal,
    })

    if (!response.ok) {
      const errText = await response.text()
      throw new Error(errText || `HTTP ${response.status}`)
    }

    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let thinkingDone = false

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed.startsWith('data: ')) continue
        try {
          const data = JSON.parse(trimmed.slice(6))
          const msg = messages.value[assistantIdx]

          if (data.type === 'thinking') {
            msg.thinking = (msg.thinking || '') + data.content
            scrollToBottom()
          } else if (data.type === 'content') {
            if (!thinkingDone && msg.thinking) {
              thinkingDone = true
            }
            msg.content += data.content
            scrollToBottom()
          } else if (data.type === 'error') {
            msg.content += `\n\n错误: ${data.content}`
          }
        } catch { /* skip */ }
      }
    }

    const finalMsg = messages.value[assistantIdx]
    if (finalMsg.thinking && !thinkingDone) {
      finalMsg.thinking = ''
    }
  } catch (e: any) {
    if (e.name === 'AbortError') {
      const msg = messages.value[assistantIdx]
      msg.content += msg.content ? '\n\n*[已停止生成]*' : '*[已停止生成]*'
    } else {
      messages.value[assistantIdx].content = `请求出错: ${e.message || String(e)}`
    }
  } finally {
    streaming.value = false
    abortController = null
    scrollToBottom()
  }
}
</script>

<style lang="scss" scoped>
.llm-chat-container {
  height: calc(100vh - 160px);
  display: flex;
  flex-direction: column;
}

.llm-chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  overflow: hidden;
  background: #f9fafb;
}

.llm-chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.llm-chat-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 8px;
  color: #c0c4cc;

  p {
    font-size: 16px;
    text-align: center;
  }

  .sub {
    font-size: 13px;
    color: #dcdfe6;
  }
}

.llm-msg {
  display: flex;
  gap: 10px;
  max-width: 100%;
  min-width: 0;

  &.user {
    align-self: flex-end;
    flex-direction: row-reverse;

    .llm-msg-user {
      background: #409eff;
      color: #fff;
      border-radius: 12px 12px 2px 12px;
      padding: 8px 14px;
      font-size: 14px;
      line-height: 1.6;
      word-break: break-word;
      max-width: 80%;
    }
  }

  &.assistant {
    align-self: flex-start;
    max-width: 100%;

    .llm-msg-assistant {
      background: #fff;
      border: 1px solid #e4e7ed;
      border-radius: 12px 12px 12px 2px;
      padding: 10px 14px;
      max-width: 100%;
      min-width: 0;
      overflow-wrap: break-word;
      word-break: break-word;
    }
  }
}

.llm-msg-avatar {
  flex-shrink: 0;
}

.llm-msg-body {
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
}

.llm-msg-thinking {
  margin-bottom: 10px;
  border: 1px solid #d9ecff;
  border-radius: 6px;
  overflow: hidden;
  background: #ecf5ff;

  .thinking-header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 12px;
    font-size: 13px;
    color: #409eff;
    font-weight: 500;
    border-bottom: 1px solid #d9ecff;

    .thinking-spin { animation: llm-rotate 1.2s linear infinite; }
  }

  .thinking-body {
    padding: 10px 12px;
    font-size: 13px;
    color: #606266;
    line-height: 1.6;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 300px;
    overflow-y: auto;
  }
}

@keyframes llm-rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.llm-msg-content {
  font-size: 14px;
  line-height: 1.7;
  overflow-wrap: break-word;
  word-break: break-word;

  :deep(pre) { white-space: pre-wrap; word-break: break-all; overflow-x: auto; max-width: 100%; }
  :deep(code) { white-space: pre-wrap; word-break: break-all; }
}

.llm-chat-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 16px;
  border-top: 1px solid #ebeef5;
  background: #fff;

  .temp-label {
    font-size: 12px;
    color: #909399;
    min-width: 40px;
  }
}

.llm-chat-input {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  padding: 12px 16px;
  border-top: 1px solid #ebeef5;
  background: #fff;

  .el-textarea { flex: 1; font-size: 14px; }
  .el-button { margin-bottom: 4px; }
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 8px 0;

  span {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #c0c4cc;
    animation: typing 1.4s infinite ease-in-out both;

    &:nth-child(1) { animation-delay: 0s; }
    &:nth-child(2) { animation-delay: 0.2s; }
    &:nth-child(3) { animation-delay: 0.4s; }
  }
}

@keyframes typing {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}
</style>

<style lang="scss">
.markdown-body {
  font-size: 14px;
  line-height: 1.8;
  color: #303133;

  h1, h2, h3, h4 { margin-top: 14px; margin-bottom: 6px; font-weight: 600; color: #1d1d1f; }
  h1 { font-size: 20px; border-bottom: 2px solid #409eff; padding-bottom: 4px; }
  h2 { font-size: 17px; border-bottom: 1px solid #e4e7ed; padding-bottom: 3px; }
  h3 { font-size: 15px; }
  p { margin: 6px 0; }
  ul, ol { padding-left: 22px; margin: 6px 0; }
  li { margin: 3px 0; }
  code {
    background: #f0f2f5; padding: 2px 5px; border-radius: 4px;
    font-family: 'Consolas', monospace; font-size: 13px; color: #d63384;
  }
  pre {
    background: #1e1e1e; border-radius: 6px; padding: 12px 16px; overflow-x: auto;
    code { background: none; color: #d4d4d4; padding: 0; }
  }
  blockquote {
    border-left: 4px solid #409eff; padding: 6px 14px; margin: 10px 0;
    background: #f0f5ff; color: #606266; border-radius: 0 6px 6px 0;
  }
  table { width: 100%; border-collapse: collapse; margin: 10px 0;
    th, td { border: 1px solid #dcdfe6; padding: 6px 10px; text-align: left; }
    th { background: #f5f7fa; font-weight: 600; }
  }
  a { color: #409eff; }
  hr { border: none; border-top: 1px solid #e4e7ed; margin: 16px 0; }
  strong { font-weight: 600; color: #1d1d1f; }
}
</style>
