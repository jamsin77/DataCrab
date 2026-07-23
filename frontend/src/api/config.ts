import api from './index'

export interface LlmConfig {
  provider: string
  api_key?: string
  api_base?: string
  model: string
  embedding_model?: string
}

export const configApi = {
  getAgentSoulMd(): Promise<{ content: string }> {
    return api.get('/config/agent/soul-md')
  },

  saveAgentSoulMd(content: string): Promise<{ content: string }> {
    return api.post('/config/agent/soul-md', { content })
  },

  getLlmConfig(): Promise<LlmConfig> {
    return api.get('/config/llm')
  },

  saveLlmConfig(data: LlmConfig): Promise<LlmConfig> {
    return api.post('/config/llm', data)
  },

  testLlm(): Promise<{ success: boolean; message?: string }> {
    return api.get('/config/llm/test')
  },
}
