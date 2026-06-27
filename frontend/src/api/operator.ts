import api from './index'

export interface Operator {
  id: string
  name: string
  display_name?: string
  category: string
  description?: string
  visibility: string
  author?: string
  script_content?: string
  created_at: string
  updated_at?: string
}

export const operatorApi = {
  list(): Promise<Operator[]> {
    return api.get('/operators')
  },

  getCategories(): Promise<string[]> {
    return api.get('/operators/categories')
  },

  upload(formData: FormData): Promise<Operator> {
    return api.post('/operators/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  delete(id: string): Promise<void> {
    return api.delete(`/operators/${id}`)
  },

  updateScript(id: string, scriptContent: string): Promise<Operator> {
    return api.put(`/operators/${id}/script`, { script_content: scriptContent })
  },

  debug(id: string, parameters: Record<string, any>, testData?: any): Promise<any> {
    return api.post(`/operators/${id}/debug`, { parameters, test_data: testData })
  },

  generate(prompt: string, timeout = 120000): Promise<Operator> {
    return api.post('/operators/generate', { prompt }, { timeout })
  },

  modify(id: string, instruction: string, timeout = 120000): Promise<Operator> {
    return api.post(`/operators/${id}/modify`, { instruction }, { timeout })
  },

  clone(id: string, name: string): Promise<Operator> {
    return api.post(`/operators/${id}/clone`, { name })
  },
}
