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

    isStreaming.value = true
    streamingContent.value = ''
    streamingReasoning.value = ''

    abortController = new AbortController()
    let aiIndex = -1

    try {
      await chatApi.sendMessageStream(
        currentSessionId.value!,
        content,
        abortController.signal,
        (event: StreamEvent) => {
          if (event.type === 'reasoning' && event.content) {
            streamingReasoning.value += event.content
          } else if (event.type === 'content' && event.content) {
            streamingContent.value += event.content
            if (aiIndex < 0) {
              const assistantMessage: ChatMessage = {
                id: `temp-ai-${Date.now()}`,
                session_id: currentSessionId.value!,
                role: 'assistant',
                content: streamingContent.value,
                reasoning: streamingReasoning.value || undefined,
                code_blocks: null,
                table_data: null,
                charts: null,
                created_at: new Date().toISOString(),
              }
              messages.value.push(assistantMessage)
              aiIndex = messages.value.length - 1
            } else {
              messages.value[aiIndex] = {
                ...messages.value[aiIndex],
                content: streamingContent.value,
                reasoning: streamingReasoning.value || undefined,
              }
            }
          }
        }
      )
      messages.value = await chatApi.listMessages(currentSessionId.value!)
    } catch (e: any) {
      if (e.name === 'AbortError') {
        if (aiIndex >= 0 && streamingContent.value) {
          messages.value[aiIndex] = {
            ...messages.value[aiIndex],
            content: streamingContent.value + '\n\n*[已停止生成]*',
          }
        }
      } else {
        if (aiIndex >= 0) {
          messages.value[aiIndex] = {
            ...messages.value[aiIndex],
            content: `请求出错: ${e.message}`,
          }
        } else {
          const errorMessage: ChatMessage = {
            id: `temp-err-${Date.now()}`,
            session_id: currentSessionId.value!,
            role: 'assistant',
            content: `请求出错: ${e.message}`,
            code_blocks: null,
            table_data: null,
            charts: null,
            created_at: new Date().toISOString(),
          }
          messages.value.push(errorMessage)
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
    fetchSessions,
    createSession,
    switchSession,
    deleteSession,
    clearMessages,
    sendMessage,
    stopGeneration,
  }
})
