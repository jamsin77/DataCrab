import api from './index'

export interface Notebook {
  id: string
  name: string
  description?: string
  cells?: NotebookCell[]
  created_by?: string
  created_at: string
  updated_at?: string
}

export interface NotebookCell {
  id: string
  cell_type: string
  source: string
  output?: any
}

export interface VariableInfo {
  name: string
  type: string
  value?: string
}

export interface NotebookVersion {
  id: string
  notebook_id: string
  version: number
  created_at: string
}

export const notebookApi = {
  list(): Promise<Notebook[]> {
    return api.get('/notebooks')
  },

  get(id: string): Promise<Notebook> {
    return api.get(`/notebooks/${id}`)
  },

  create(data: { name: string; description?: string }): Promise<Notebook> {
    return api.post('/notebooks', data)
  },

  update(id: string, data: Partial<Notebook>): Promise<Notebook> {
    return api.put(`/notebooks/${id}`, data)
  },

  delete(id: string): Promise<void> {
    return api.delete(`/notebooks/${id}`)
  },

  executeCell(id: string, cellId: string): Promise<any> {
    return api.post(`/notebooks/${id}/execute`, { cell_id: cellId })
  },

  restartKernel(id: string): Promise<void> {
    return api.post(`/notebooks/${id}/kernel/restart`)
  },

  getVariables(id: string): Promise<VariableInfo[]> {
    return api.get(`/notebooks/${id}/variables`)
  },

  getVersions(id: string): Promise<NotebookVersion[]> {
    return api.get(`/notebooks/${id}/versions`)
  },
}
