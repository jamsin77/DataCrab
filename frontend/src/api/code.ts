import api from './index'

export interface CodeEntry {
  id: string
  name?: string
  description?: string
  code?: string
  language?: string
  status?: string
  created_at: string
  updated_at?: string
}

export const codeApi = {
  list(): Promise<CodeEntry[]> {
    return api.get('/codes')
  },

  generate(nlDescription: string): Promise<CodeEntry> {
    return api.post('/codes/generate', { nl_description: nlDescription })
  },

  execute(id: string): Promise<any> {
    return api.post(`/codes/${id}/execute`)
  },
}
