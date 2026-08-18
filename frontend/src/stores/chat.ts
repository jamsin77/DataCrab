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

  async function sendMessage(content: string, attachments?: { filename: string; table_name_prefix?: string; sheets?: string[] }[]) {
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
      attachments: attachments && attachments.length ? attachments : undefined,
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
      execLogs: [],
    }
    messages.value.push(assistantMessage)
    const aiIndex = messages.value.length - 1

    isStreaming.value = true
    streamingContent.value = ''
    streamingReasoning.value = ''

    abortController = new AbortController()

    // 归档执行日志：把当前 executingMsg 推入 execLogs，再清空
    const archiveExec = (msg: ChatMessage | undefined) => {
      if (!msg) return
      if (msg.executingMsg) {
        if (!msg.execLogs) msg.execLogs = []
        msg.execLogs.push(msg.executingMsg)
        msg.executingMsg = ''
      }
    }

    // 提取文件名给后端
    const attFilenames = attachments?.map(a => a.filename)

    try {
      await chatApi.sendMessageStream(
        currentSessionId.value!,
        content,
        abortController.signal,
        (event: StreamEvent) => {
          const msg = messages.value[aiIndex]
          if (!msg) return

          if (event.type === 'error') {
            archiveExec(msg)
            msg.content = (msg.content || '') + `\n\n❌ ${event.content || '未知错误'}`
            return
          }
          if (event.type === 'done') {
            archiveExec(msg)
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
            archiveExec(msg)
          } else if (event.type === 'progress' || event.type === 'executing') {
            archiveExec(msg)
            msg.executingMsg = event.message || event.content || ''
          } else if (event.type === 'agent_switch') {
            const _name = (event as any).display_name || event.agent || ''
            const _reason = (event as any).reason_display || event.reason || ''
            archiveExec(msg)
            msg.executingMsg = _reason ? `${_name}：${_reason}` : _name
            msg.agentName = _name
          } else if (event.type === 'tool_action') {
            const _actions = (event as any).actions || []
            const _lines = _actions.map((a: any) => `${a.icon || '🔧'} ${a.tool}${a.detail ? ': ' + a.detail : ''}`)
            archiveExec(msg)
            msg.executingMsg = _lines.join(' | ')
          } else if (event.type === 'tool_summary') {
            const _summaries = (event as any).summaries || []
            archiveExec(msg)
            msg.executingMsg = _summaries.join(' | ')
          } else if (event.type === 'inspecting' || event.type === 'retry') {
            archiveExec(msg)
            msg.executingMsg = event.message || ''
          } else if (event.type === 'round') {
            archiveExec(msg)
            msg.executingMsg = event.message || `第 ${event.round} 次修改`
          } else if (event.type === 'inspection_report') {
            msg.inspectionReport = event.report || ''
          }
        },
        attFilenames,
      )
      // 流式结束后从 DB 刷新（同步历史，避免 temp ID 残留）
      // 保留前端临时字段（inspectionReport/reasoning/model/execLogs/attachments），DB 里没有这些字段
      const _savedReport = messages.value[aiIndex]?.inspectionReport
      const _savedReasoning = messages.value[aiIndex]?.reasoning
      const _savedModel = messages.value[aiIndex]?.model
      const _savedExecLogs = messages.value[aiIndex]?.execLogs
      const _savedUserIdx = aiIndex - 1
      const _savedUserAtts = messages.value[_savedUserIdx]?.attachments
      messages.value = await chatApi.listMessages(currentSessionId.value!)
      // 找刷新后的最后一条 assistant 消息，回填临时字段
      const _lastAssistant = [...messages.value].reverse().find(m => m.role === 'assistant')
      if (_lastAssistant) {
        if (_savedReport) _lastAssistant.inspectionReport = _savedReport
        if (_savedReasoning && !_lastAssistant.reasoning) _lastAssistant.reasoning = _savedReasoning
        if (_savedModel && !_lastAssistant.model) _lastAssistant.model = _savedModel
        if (_savedExecLogs && _savedExecLogs.length) _lastAssistant.execLogs = _savedExecLogs
      }
      // 回填用户消息附件
      const _lastUser = [...messages.value].reverse().find(m => m.role === 'user')
      if (_lastUser && _savedUserAtts) {
        _lastUser.attachments = _savedUserAtts
      }
    } catch (e: any) {
      const msg = messages.value[aiIndex]
      if (msg) {
        archiveExec(msg)
        if (e.name === 'AbortError') {
          if (msg.content) {
            msg.content += '\n\n*[已停止生成]*'
          } else {
            msg.content = '*[已停止生成]*'
          }
        } else {
          const errDetail = e.message || String(e)
          const errStack = e.stack ? `\n\n堆栈:\n${e.stack.split('\n').slice(0, 5).join('\n')}` : ''
          msg.content = (msg.content || '') + `\n\n❌ 请求出错: ${errDetail}${errStack}`
        }
      }
    } finally {
      // 清除转圈指示，但保留 execLogs（折叠显示）
      messages.value.forEach(m => { m.executingMsg = '' })
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
