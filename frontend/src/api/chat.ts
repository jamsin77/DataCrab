import api from './index'

export interface ChatSession {
  id: string
  user_id: string
  title: string | null
  context?: Record<string, any> | null
  created_at: string
  updated_at: string | null
}

export interface ChatMessage {
  id: string
  session_id: string
  role: 'user' | 'assistant'
  content: string
  reasoning?: string
  model?: string
  code_blocks: any[] | null
  table_data: any | null
  charts: any[] | null
  meta?: Record<string, any> | null  // 后端持久化的临时字段（model/reasoning/executingMsgs/suggestion 等）
  created_at: string
  executingMsg?: string
  executingMsgs?: string[]       // 实时执行进度（逐行显示，最后一行带转圈）
  inspectionReport?: string
  agentName?: string  // 当前处理智能体中文名（如"数据分析师"）
  attachments?: { filename: string; table_name_prefix?: string; sheets?: string[] }[]  // 用户消息附件元信息
  suggestion?: { type: string; matches: any[] }  // 技能/流程/数据匹配建议
  noMatch?: boolean  // 无匹配标记
  missingParams?: string[]  // 缺少的参数
  msgType?: string  // 消息类型（analysis/processing/chat）
  _suggestionConsumed?: boolean  // 前端标记：建议已被消费（如选择了数据）
}

export interface StreamEvent {
  type: 'reasoning' | 'thinking' | 'content' | 'model' | 'done' | 'error' | 'cancelled' | 'ping' | 'agent_switch' | 'tool_result' | 'round' | 'clear_thinking' | [key: string]
  content?: string
  agent?: string
  reason?: string
  message?: string
}

export const chatApi = {
  createSession(title?: string): Promise<ChatSession> {
    return api.post('/chat/sessions', { title })
  },

  listSessions(skip = 0, limit = 20): Promise<ChatSession[]> {
    return api.get('/chat/sessions', { params: { skip, limit } })
  },

  getSession(sessionId: string): Promise<ChatSession> {
    return api.get(`/chat/sessions/${sessionId}`)
  },

  updateSession(sessionId: string, title: string): Promise<ChatSession> {
    return api.put(`/chat/sessions/${sessionId}`, { title })
  },

  updateSessionContext(sessionId: string, context: Record<string, any>): Promise<ChatSession> {
    return api.patch(`/chat/sessions/${sessionId}/context`, context)
  },

  deleteSession(sessionId: string): Promise<void> {
    return api.delete(`/chat/sessions/${sessionId}`)
  },

  listMessages(sessionId: string): Promise<ChatMessage[]> {
    return api.get(`/chat/sessions/${sessionId}/messages`)
  },

  clearMessages(sessionId: string): Promise<void> {
    return api.delete(`/chat/sessions/${sessionId}/messages`)
  },

  updateMessageMetadata(messageId: string, metadata: Record<string, any>): Promise<void> {
    return api.patch(`/chat/messages/${messageId}/metadata`, metadata)
  },

  stopGeneration(sessionId: string): Promise<void> {
    return api.post('/chat/stop', null, { params: { session_id: sessionId } })
  },

  uploadAttachment(file: File, sessionId?: string): Promise<{
    datasource_id: string
    name: string
    filename: string
    table_name_prefix: string
    size_bytes: number
    sheets: string[]
    columns: string[]
  }> {
    const formData = new FormData()
    formData.append('file', file)
    const params = sessionId ? `?session_id=${sessionId}` : ''
    return api.post(`/chat/upload${params}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  async sendMessageStream(
    sessionId: string,
    content: string,
    signal: AbortSignal,
    onEvent: (event: StreamEvent) => void,
    directExecute?: boolean,
    selectedDatasourceId?: string,
    selectedTableName?: string,
    targetDatasourceId?: string,
    targetTableName?: string,
    targetWriteMode?: string,
    selectedSkillId?: string,
    selectedSkillName?: string,
    selectedSkillType?: string,
    useSkill?: boolean,
  ): Promise<void> {
    const token = localStorage.getItem('access_token')

    const response = await fetch('/api/v1/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        session_id: sessionId,
        content,
        direct_execute: directExecute || false,
        use_skill: useSkill || false,
        selected_datasource_id: selectedDatasourceId || null,
        selected_table_name: selectedTableName || null,
        target_datasource_id: targetDatasourceId || null,
        target_data_name: targetTableName || null,
        target_write_mode: targetWriteMode || null,
        selected_skill_id: selectedSkillId || null,
        selected_skill_name: selectedSkillName || null,
        selected_skill_type: selectedSkillType || null,
      }),
      signal,
    })

    if (!response.ok) {
      let errText = ''
      try {
        errText = await response.text()
        try {
          const errJson = JSON.parse(errText)
          if (errJson.detail) {
            if (Array.isArray(errJson.detail)) {
              errText = errJson.detail.map((d: any) => `${d.loc?.join('.') || d.type}: ${d.msg}`).join('; ')
            } else {
              errText = typeof errJson.detail === 'string' ? errJson.detail : JSON.stringify(errJson.detail)
            }
          }
        } catch { /* not JSON, keep raw */ }
      } catch { /* read body failed */ }
      // 通过 onEvent 推送 error 事件，确保前端能显示
      onEvent({ type: 'error', content: errText || `HTTP ${response.status}` })
      return
    }

    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let gotDone = false

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
          const data = JSON.parse(trimmed.slice(6)) as StreamEvent
          onEvent(data)

          if (data.type === 'done' || data.type === 'error' || data.type === 'cancelled') {
            gotDone = true
            return
          }
        } catch {
          // skip malformed JSON lines
        }
      }
    }

    // 流结束但没收到 done/error 事件 → 后端异常断开
    if (!gotDone) {
      throw new Error('服务端连接异常断开，未收到完整响应')
    }
  },
}
