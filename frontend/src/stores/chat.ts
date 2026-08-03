import { defineStore } from 'pinia'
import { ref } from 'vue'
import { chatApi, type ChatSession, type ChatMessage, type StreamEvent } from '@/api/chat'

export const useChatStore = defineStore('chat', () => {
  const sessions = ref<ChatSession[]>([])
  const currentSessionId = ref<string | null>(null)
  const messages = ref<ChatMessage[]>([])
  const isStreaming = ref(false)
  const streamingContent = ref('')
  const streamingReasoning = ref('')
  const currentModel = ref('')
  let abortController: AbortController | null = null

  async function fetchSessions() {
    sessions.value = await chatApi.listSessions()
  }

  async function createSession() {
    const session = await chatApi.createSession()
    sessions.value.unshift(session)
    currentSessionId.value = session.id
    messages.value = []
    return session
  }

  async function switchSession(sessionId: string) {
    currentSessionId.value = sessionId
    messages.value = await chatApi.listMessages(sessionId)
  }

  async function deleteSession(sessionId: string) {
    await chatApi.deleteSession(sessionId)
    sessions.value = sessions.value.filter((s) => s.id !== sessionId)
    if (currentSessionId.value === sessionId) {
      currentSessionId.value = sessions.value.length > 0 ? sessions.value[0].id : null
      if (currentSessionId.value) {
        messages.value = await chatApi.listMessages(currentSessionId.value)
      } else {
        messages.value = []
      }
    }
  }

  async function clearMessages() {
    if (!currentSessionId.value) return
    await chatApi.clearMessages(currentSessionId.value)
    messages.value = []
  }

  async function sendMessage(content: string) {
    if (!currentSessionId.value) {
      await createSession()
    }

    const userMessage: ChatMessage = {
      id: `temp-usr-${Date.now()}`,
      session_id: currentSessionId.value!,
      role: 'user',
      content,
      code_blocks: null,
      table_data: null,
      charts: null,
      created_at: new Date().toISOString(),
    }
    messages.value.push(userMessage)

    // 提前创建 assistant 消息（和技能调试一样），流式事件直接更新它
    const assistantMessage: ChatMessage = {
      id: `temp-ai-${Date.now()}`,
      session_id: currentSessionId.value!,
      role: 'assistant',
      content: '',
      reasoning: undefined,
      model: undefined,
      code_blocks: null,
      table_data: null,
      charts: null,
      created_at: new Date().toISOString(),
    }
    messages.value.push(assistantMessage)
    const aiIndex = messages.value.length - 1

    isStreaming.value = true
    streamingContent.value = ''
    streamingReasoning.value = ''

    abortController = new AbortController()

    try {
      await chatApi.sendMessageStream(
        currentSessionId.value!,
        content,
        abortController.signal,
        (event: StreamEvent) => {
          const msg = messages.value[aiIndex]
          if (!msg) return

          if (event.type === 'error') {
            msg.content = (msg.content || '') + `\n\n❌ ${event.content || '未知错误'}`
            return
          }
          if (event.type === 'model') {
            msg.model = event.content || ''
            currentModel.value = event.content || ''
            return
          }
          if (event.type === 'clear_thinking') {
            msg.reasoning = ''
            msg.content = ''
            streamingReasoning.value = ''
            streamingContent.value = ''
            return
          }
          if ((event.type === 'reasoning' || event.type === 'thinking') && event.content) {
            msg.reasoning = (msg.reasoning || '') + event.content
            streamingReasoning.value = msg.reasoning || ''
          } else if (event.type === 'content' && event.content) {
            msg.content = (msg.content || '') + event.content
            streamingContent.value = msg.content
          }
        }
      )
      // 流式结束后从 DB 刷新（同步历史，避免 temp ID 残留）
      messages.value = await chatApi.listMessages(currentSessionId.value!)
    } catch (e: any) {
      const msg = messages.value[aiIndex]
      if (msg) {
        if (e.name === 'AbortError') {
          if (msg.content) {
            msg.content += '\n\n*[已停止生成]*'
          }
        } else {
          const errDetail = e.message || String(e)
          const errStack = e.stack ? `\n\n堆栈:\n${e.stack.split('\n').slice(0, 5).join('\n')}` : ''
          msg.content = (msg.content || '') + `\n\n❌ 请求出错: ${errDetail}${errStack}`
        }
      }
    } finally {
      isStreaming.value = false
      abortController = null
    }
  }

  async function stopGeneration() {
    if (abortController) {
      abortController.abort()
    }
    if (currentSessionId.value) {
      await chatApi.stopGeneration(currentSessionId.value).catch(() => {})
    }
    isStreaming.value = false
  }

  return {
    sessions,
    currentSessionId,
    messages,
    isStreaming,
    streamingContent,
    streamingReasoning,
    currentModel,
    fetchSessions,
    createSession,
    switchSession,
    deleteSession,
    clearMessages,
    sendMessage,
    stopGeneration,
  }
})
