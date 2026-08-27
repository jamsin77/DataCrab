import { defineStore } from 'pinia'
import { ref } from 'vue'
import { chatApi, type ChatSession, type ChatMessage, type StreamEvent } from '@/api/chat'

function nowStr(): string {
  return new Date().toLocaleString('zh-CN', { hour12: false, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function pushExecMsg(msg: any, text: string) {
  if (!text) return
  if (!msg.executingMsgs) msg.executingMsgs = []
  msg.executingMsgs.push(`${nowStr()} ${text}`)
}

export const useChatStore = defineStore('chat', () => {
  const sessions = ref<ChatSession[]>([])
  const currentSessionId = ref<string | null>(null)
  const messages = ref<ChatMessage[]>([])
  const isStreaming = ref(false)
  const streamingContent = ref('')
  const streamingReasoning = ref('')
  const currentModel = ref('')
  const selectedData = ref<{ datasource_id: string; datasource_name: string; table_name: string } | null>(null)
  let abortController: AbortController | null = null

  function _restoreMetadata(msgs: ChatMessage[]) {
    for (const msg of msgs) {
      if (!msg.meta) continue
      if (msg.meta.model) msg.model = msg.meta.model
      if (msg.meta.reasoning) msg.reasoning = msg.meta.reasoning
      if (msg.meta.executingMsgs) msg.executingMsgs = msg.meta.executingMsgs
      if (msg.meta.agentName) msg.agentName = msg.meta.agentName
      if (msg.meta.suggestion) msg.suggestion = msg.meta.suggestion
      if (msg.meta.suggestionConsumed) msg._suggestionConsumed = true
      if (msg.meta.inspectionReport) msg.inspectionReport = msg.meta.inspectionReport
      if (msg.meta.noMatch) msg.noMatch = true
    }
  }

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
    if (isStreaming.value && currentSessionId.value !== sessionId) {
      await stopGeneration()
    }
    currentSessionId.value = sessionId
    messages.value = await chatApi.listMessages(sessionId)
    _restoreMetadata(messages.value)
    // 从会话 context 恢复已选数据源/表（刷新/重开不丢）
    const _sess = sessions.value.find((s) => s.id === sessionId)
    const _ctx = _sess?.context
    if (_ctx && _ctx.source_datasource_id && _ctx.source_datasource_name) {
      selectedData.value = {
        datasource_id: _ctx.source_datasource_id,
        datasource_name: _ctx.source_datasource_name,
        table_name: _ctx.source_table_name || '',
      }
    } else {
      selectedData.value = null
    }
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
      reasoning: '',
      model: '',
      code_blocks: null,
      table_data: null,
      charts: null,
      created_at: new Date().toISOString(),
    }
    messages.value.push(assistantMessage)
    const aiIndex = messages.value.length - 1
    const sessionId = currentSessionId.value!

    isStreaming.value = true
    streamingContent.value = ''
    streamingReasoning.value = ''

    abortController = new AbortController()

    // 提取文件名给后端
    const attFilenames = attachments?.map(a => a.filename)
    // 携带用户选择的数据（从 data_suggestion 选择后发送消息时带上）
    const _selDs = selectedData.value?.datasource_id
    const _selTbl = selectedData.value?.table_name

    // 保存临时字段 → 从 DB 刷新 → 恢复临时字段 → 持久化 meta（正常完成和 AbortError 共用）
    async function _syncFromDB() {
      if (currentSessionId.value !== sessionId) return
      const msg = messages.value[aiIndex]
      if (!msg) return
      const _savedReport = msg.inspectionReport
      const _savedReasoning = msg.reasoning
      const _savedModel = msg.model
      const _savedExecMsgs = msg.executingMsgs
      const _savedAgentName = msg.agentName
      const _savedSuggestion = msg.suggestion
      const _savedSuggestionConsumed = msg._suggestionConsumed
      const _savedNoMatch = msg.noMatch
      const _savedUserAtts = messages.value[aiIndex - 1]?.attachments
      try {
        messages.value = await chatApi.listMessages(currentSessionId.value!)
        _restoreMetadata(messages.value)
        const _lastAssistant = [...messages.value].reverse().find(m => m.role === 'assistant')
        if (_lastAssistant) {
          if (_savedReport) _lastAssistant.inspectionReport = _savedReport
          if (_savedReasoning) _lastAssistant.reasoning = _savedReasoning
          if (_savedModel) _lastAssistant.model = _savedModel
          if (_savedExecMsgs && _savedExecMsgs.length) _lastAssistant.executingMsgs = _savedExecMsgs
          if (_savedAgentName) _lastAssistant.agentName = _savedAgentName
          if (_savedSuggestion) _lastAssistant.suggestion = _savedSuggestion
          if (_savedSuggestionConsumed) _lastAssistant._suggestionConsumed = true
          if (_savedNoMatch) _lastAssistant.noMatch = true
          const _meta: Record<string, any> = {}
          if (_savedModel) _meta.model = _savedModel
          if (_savedReasoning) _meta.reasoning = _savedReasoning
          if (_savedExecMsgs?.length) _meta.executingMsgs = _savedExecMsgs
          if (_savedAgentName) _meta.agentName = _savedAgentName
        if (_savedSuggestion) _meta.suggestion = _savedSuggestion
        if (_savedSuggestionConsumed) _meta.suggestionConsumed = true
        if (_savedReport) _meta.inspectionReport = _savedReport
          if (_savedNoMatch) _meta.noMatch = true
          if (Object.keys(_meta).length > 0) {
            chatApi.updateMessageMetadata(_lastAssistant.id, _meta).catch(() => {})
          }
        }
        const _lastUser = [...messages.value].reverse().find(m => m.role === 'user')
        if (_lastUser && _savedUserAtts) {
          _lastUser.attachments = _savedUserAtts
        }
      } catch {
        // DB 刷新失败（后端可能还没保存完），用前端已有内容
        if (msg.content) {
          msg.content += '\n\n*[已停止生成]*'
        } else {
          msg.content = '*[已停止生成]*'
        }
      }
    }

    try {
      await chatApi.sendMessageStream(
        currentSessionId.value!,
        content,
        abortController.signal,
        (event: StreamEvent) => {
          if (currentSessionId.value !== sessionId) return
          const msg = messages.value[aiIndex]
          if (!msg) return

          if (event.type === 'error') {
            msg.content = (msg.content || '') + `\n\n❌ ${event.content || '未知错误'}`
            return
          }
          if (event.type === 'done') {
            return
          }
          if (event.type === 'data_suggestion' || event.type === 'skill_suggestion' || event.type === 'target_suggestion') {
            const _data = event as any
            if (!msg.suggestions) msg.suggestions = []
            msg.suggestions.push({ type: _data.type, msg_type: _data.msg_type, matches: _data.matches || [] })
            msg.suggestion = { type: _data.type, msg_type: _data.msg_type, matches: _data.matches || [] }
            return
          }
          if (event.type === 'no_match') {
            msg.noMatch = true
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
          } else if (event.type === 'progress' || event.type === 'executing') {
            const _m = event.message || event.content || ''
            pushExecMsg(msg, _m)
          } else if (event.type === 'agent_switch') {
            const _name = (event as any).display_name || event.agent || ''
            const _reason = (event as any).reason_display || event.reason || ''
            const _m = _reason ? `${_name}：${_reason}` : _name
            pushExecMsg(msg, _m)
            msg.agentName = _name
          } else if (event.type === 'tool_action') {
            const _actions = (event as any).actions || []
            const _lines = _actions.map((a: any) => `${a.icon || '🔧'} ${a.tool}${a.detail ? ': ' + a.detail : ''}`)
            pushExecMsg(msg, _lines.join(' | '))
          } else if (event.type === 'tool_summary') {
            const _summaries = (event as any).summaries || []
            pushExecMsg(msg, _summaries.join(' | '))
          } else if (event.type === 'inspecting' || event.type === 'retry') {
            const _m = event.message || ''
            pushExecMsg(msg, _m)
          } else if (event.type === 'round') {
            const _m = event.message || `第 ${event.round} 次修改`
            pushExecMsg(msg, _m)
          } else if (event.type === 'inspection_report') {
            msg.inspectionReport = event.report || ''
          }
        },
        attFilenames,
        _selDs,
        _selTbl,
      )
      // 发送后清除选择的数据
      selectedData.value = null
      await _syncFromDB()
    } catch (e: any) {
      if (currentSessionId.value !== sessionId) return
      const msg = messages.value[aiIndex]
      if (msg) {
        archiveExec(msg)
        if (e.name === 'AbortError') {
          // 后端已保存 partial content，从 DB 刷新 + 持久化临时字段
          await _syncFromDB()
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

  async function sendDirectly(content: string, attachments?: { filename: string; table_name_prefix?: string; sheets?: string[] }[]) {
    await sendMessage(content, attachments)
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
    selectedData,
    fetchSessions,
    createSession,
    switchSession,
    deleteSession,
    clearMessages,
    sendMessage,
    sendDirectly,
    stopGeneration,
  }
})
