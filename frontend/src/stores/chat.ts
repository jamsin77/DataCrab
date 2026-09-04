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
  messages.value = [...messages.value]
}

export const useChatStore = defineStore('chat', () => {
  const sessions = ref<ChatSession[]>([])
  const currentSessionId = ref<string | null>(null)
  const messages = ref<ChatMessage[]>([])
  const isStreaming = ref(false)
  const streamingContent = ref('')
  const streamingReasoning = ref('')
  const currentModel = ref('')
  const selectedData = ref<{ datasource_id: string; datasource_name: string; table_name: string; target_datasource_id?: string; target_datasource_name?: string; target_table_name?: string; target_write_mode?: string; skill_id?: string; skill_name?: string; skill_type?: string } | null>(null)
  let abortController: AbortController | null = null

  function _restoreMetadata(msgs: ChatMessage[]) {
    for (const msg of msgs) {
      if (!msg.meta) continue
      if (msg.meta.model) msg.model = msg.meta.model
      if (msg.meta.reasoning) msg.reasoning = msg.meta.reasoning
      if (msg.meta.executingMsgs) msg.executingMsgs = msg.meta.executingMsgs
      if (msg.meta.agentName) msg.agentName = msg.meta.agentName
      if (msg.meta.suggestion) msg.suggestion = msg.meta.suggestion
      if (msg.meta.suggestions) msg.suggestions = msg.meta.suggestions
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
    selectedData.value = null
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
        table_name: _ctx.source_data_name || _ctx.source_table_name || '',
        filename: _ctx.source_filename || _ctx.source_data_name || _ctx.source_table_name || '',
        target_datasource_id: _ctx.target_datasource_id || undefined,
        target_datasource_name: _ctx.target_datasource_name || undefined,
        target_table_name: _ctx.target_data_name || _ctx.target_table_name || undefined,
        target_filename: _ctx.target_filename || _ctx.target_data_name || _ctx.target_table_name || undefined,
        target_write_mode: _ctx.target_write_mode || undefined,
        skill_id: _ctx.last_skill_id || undefined,
        skill_name: _ctx.last_skill_name || undefined,
        skill_type: _ctx.last_skill_type || undefined,
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

  async function sendMessage(content: string, directExecute = false, reuseLastMessage = false, useSkill = false) {
    if (!currentSessionId.value) {
      await createSession()
    }

    let aiIndex: number
    if (directExecute || reuseLastMessage) {
      // directExecute：复用最后一条 assistant 消息，不 push 重复的用户消息
      const lastIdx = messages.value.length - 1
      const lastMsg = messages.value[lastIdx]
      if (lastMsg && lastMsg.role === 'assistant') {
        // 清空旧内容，准备接收新流式数据
        lastMsg.content = ''
        lastMsg.reasoning = ''
        lastMsg.model = ''
        lastMsg.executingMsgs = []
        lastMsg.agentName = ''
        lastMsg.inspectionReport = ''
        lastMsg.suggestions = undefined
        lastMsg.suggestion = undefined
        lastMsg._newTableName = undefined
        lastMsg._selectedTarget = undefined
        lastMsg._writeMode = undefined
        aiIndex = lastIdx
      } else {
        // 没有 assistant 消息可复用，push 一条
        messages.value.push({
          id: `temp-ai-${Date.now()}`,
          session_id: currentSessionId.value!,
          role: 'assistant',
          content: '', reasoning: '', model: '',
          code_blocks: null, table_data: null, charts: null,
          created_at: new Date().toISOString(),
        } as ChatMessage)
        aiIndex = messages.value.length - 1
      }
    } else {
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
      aiIndex = messages.value.length - 1
    }
    const sessionId = currentSessionId.value!

    isStreaming.value = true
    streamingContent.value = ''
    streamingReasoning.value = ''

    abortController = new AbortController()

    // 携带用户选择的数据（从 data_suggestion / target_suggestion / skill_suggestion 选择后发送消息时带上）
    const _selDs = selectedData.value?.datasource_id
    const _selTbl = selectedData.value?.table_name
    const _tgtDs = selectedData.value?.target_datasource_id
    const _tgtTbl = selectedData.value?.target_table_name
    const _tgtMode = selectedData.value?.target_write_mode
    const _skillId = selectedData.value?.skill_id
    const _skillName = selectedData.value?.skill_name
    const _skillType = selectedData.value?.skill_type

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
      const _savedSuggestions = msg.suggestions
      console.log('[chat] _syncFromDB saving suggestions:', _savedSuggestions?.length, _savedSuggestions?.map((s:any)=>s.type))
      const _savedConsumedSuggestions = msg._consumedSuggestions
      const _savedSuggestionConsumed = msg._suggestionConsumed
      const _savedNoMatch = msg.noMatch
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
          if (_savedSuggestions) _lastAssistant.suggestions = _savedSuggestions
          if (_savedConsumedSuggestions) _lastAssistant._consumedSuggestions = _savedConsumedSuggestions
          console.log('[chat] _syncFromDB restored suggestions:', _lastAssistant.suggestions?.length, _lastAssistant.suggestions?.map((s:any)=>s.type))
          if (_savedSuggestionConsumed) _lastAssistant._suggestionConsumed = true
          if (_savedNoMatch) _lastAssistant.noMatch = true
          const _meta: Record<string, any> = {}
          if (_savedModel) _meta.model = _savedModel
          if (_savedReasoning) _meta.reasoning = _savedReasoning
          if (_savedExecMsgs?.length) _meta.executingMsgs = _savedExecMsgs
          if (_savedAgentName) _meta.agentName = _savedAgentName
        if (_savedSuggestion) _meta.suggestion = _savedSuggestion
        if (_savedSuggestions) _meta.suggestions = _savedSuggestions
        if (_savedSuggestionConsumed) _meta.suggestionConsumed = true
        if (_savedReport) _meta.inspectionReport = _savedReport
          if (_savedNoMatch) _meta.noMatch = true
          if (Object.keys(_meta).length > 0) {
            chatApi.updateMessageMetadata(_lastAssistant.id, _meta).catch(() => {})
          }
        }
        // 恢复完临时字段后触发响应式更新
        messages.value = [...messages.value]
      } catch (e: any) {
        // DB 刷新失败——后端可能挂了或请求异常
        const _reason = e?.message || String(e)
        if (msg.content) {
          msg.content += `\n\n❌ 服务连接失败：${_reason}`
        } else {
          msg.content = `❌ 服务连接失败：${_reason}`
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
            streamingContent.value = msg.content
            messages.value = [...messages.value]
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
            console.log('[chat] suggestion event:', _data.type, 'total suggestions:', msg.suggestions.length, JSON.stringify(msg.suggestions.map((s:any)=>s.type)))
            messages.value = [...messages.value]
            return
          }
          if (event.type === 'source_datasource_no_match' || event.type === 'source_table_no_match' || event.type === 'target_datasource_no_match') {
            const _data = event as any
            // 数据源/数据表未匹配到：提示放 content，不渲染卡片
            if (_data.type === 'source_datasource_no_match') {
              msg.content = (msg.content ? msg.content + '\n\n' : '') + '缺少源数据源，请指定'
            } else if (_data.type === 'source_table_no_match') {
              msg.content = (msg.content ? msg.content + '\n\n' : '') + '缺少源数据表，请指定'
            } else if (_data.type === 'target_datasource_no_match') {
              msg.content = (msg.content ? msg.content + '\n\n' : '') + '缺少目标数据源，请指定'
            }
            messages.value = [...messages.value]
            return
          }
          if (event.type === 'target_table_no_match') {
            // 目标表不存在 → 渲染新建表名输入框卡片
            if (!msg.suggestions) msg.suggestions = []
            msg.suggestions.push({ type: 'target_table_no_match', msg_type: (event as any).msg_type })
            messages.value = [...messages.value]
            return
          }
          if (event.type === 'skill_no_match') {
            const _data = event as any
            if (!msg.suggestions) msg.suggestions = []
            msg.suggestions.push({ type: _data.type, msg_type: _data.msg_type || '' })
            messages.value = [...messages.value]
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
        directExecute,
        _selDs,
        _selTbl,
        _tgtDs,
        _tgtTbl,
        _tgtMode,
        _skillId,
        _skillName,
        _skillType,
        useSkill,
      )
      if (!directExecute) {
        await _syncFromDB()
      } else {
        // directExecute 跳过从 DB 刷新（避免重复用户消息），但仍持久化 meta（executingMsgs/suggestions 等）
        const msg = messages.value[aiIndex]
        if (msg) {
          const _meta: Record<string, any> = {}
          if (msg.executingMsgs?.length) _meta.executingMsgs = msg.executingMsgs
          if (msg.model) _meta.model = msg.model
          if (msg.agentName) _meta.agentName = msg.agentName
          if (msg.suggestion) _meta.suggestion = msg.suggestion
          if (msg.suggestions?.length) _meta.suggestions = msg.suggestions
          if (msg.inspectionReport) _meta.inspectionReport = msg.inspectionReport
          if (msg.noMatch) _meta.noMatch = true
          const _realId = msg.id.startsWith('temp-') ? null : msg.id
          if (_realId && Object.keys(_meta).length > 0) {
            chatApi.updateMessageMetadata(_realId, _meta).catch(() => {})
          }
        }
      }
    } catch (e: any) {
      console.error('[chat] sendMessage error:', e)
      if (currentSessionId.value !== sessionId) return
      const msg = messages.value[aiIndex]
      if (msg) {
        archiveExec(msg)
        if (e.name === 'AbortError') {
          // 后端已保存 partial content，从 DB 刷新 + 持久化临时字段
          if (!directExecute) {
            await _syncFromDB()
          }
        } else {
          const errDetail = e.message || String(e)
          // 直接设置 content，触发 Vue 响应式更新
          msg.content = `\n\n❌ 请求出错: ${errDetail}`
          // 触发数组更新确保渲染
          messages.value = [...messages.value]
          // 422/网络错误时后端可能没保存消息，不调 _syncFromDB（会用 DB 旧数据覆盖前端错误提示）
        }
      }
    } finally {
      isStreaming.value = false
      abortController = null
    }
  }

  async function sendDirectly(content: string) {
    await sendMessage(content, true)
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
