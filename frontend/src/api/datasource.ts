import api from './index'

export interface DataSource {
  id: string
  name: string
  type: string
  connection_config: Record<string, any>
  visibility?: string
  created_by?: string
  created_at: string
  updated_at?: string
}

export interface TableNode {
  name: string
  type: string
  children?: TableNode[]
}

export const datasourceApi = {
  list(type?: string): Promise<DataSource[]> {
    return api.get('/datasources', { params: type ? { type } : undefined })
  },

  create(data: { name: string; type: string; connection_config: Record<string, any> }): Promise<DataSource> {
    return api.post('/datasources', data)
  },

  update(id: string, data: { name: string; connection_config: Record<string, any> }): Promise<DataSource> {
    return api.put(`/datasources/${id}`, data)
  },

  delete(id: string): Promise<void> {
    return api.delete(`/datasources/${id}`)
  },

  testConnection(id: string): Promise<any> {
    return api.post(`/datasources/${id}/test`)
  },

  getTree(id: string): Promise<TableNode[]> {
    return api.get(`/datasources/${id}/tree`)
  },

  getTableData(id: string, tableName: string, page = 1, pageSize = 50): Promise<any> {
    return api.get(`/datasources/${id}/tables/${tableName}/data`, {
      params: { page, page_size: pageSize },
    })
  },
}
