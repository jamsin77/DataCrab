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

  uploadAttachment(file: File): Promise<{
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
    return api.post('/chat/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  async sendMessageStream(
    sessionId: string,
    content: string,
    signal: AbortSignal,
    onEvent: (event: StreamEvent) => void,
    attachments?: string[],
    skipMatch?: boolean,
    skipSteps?: string[],
    selectedDatasourceId?: string,
    selectedTableName?: string,
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
        attachments,
        skip_match: skipMatch || false,
        skip_steps: skipSteps || [],
        selected_datasource_id: selectedDatasourceId || null,
        selected_table_name: selectedTableName || null,
      }),
      signal,
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
          const data = JSON.parse(trimmed.slice(6)) as StreamEvent
          onEvent(data)

          if (data.type === 'done' || data.type === 'error' || data.type === 'cancelled') {
            return
          }
        } catch {
          // skip malformed JSON lines
        }
      }
    }
  },
}
