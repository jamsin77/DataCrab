import api from './index'

export interface FileLink {
  id: string
  name: string
  path: string
  description?: string
  is_public: boolean
  allowed_extensions?: string
  created_by?: string
  created_at: string
  updated_at?: string
}

export interface FileEntry {
  name: string
  type: 'file' | 'directory'
  size?: number
  modified?: string
}

export const filelinkApi = {
  list(): Promise<FileLink[]> {
    return api.get('/filelinks')
  },

  create(data: { name: string; path: string; description?: string; is_public: boolean; allowed_extensions?: string }): Promise<FileLink> {
    return api.post('/filelinks', data)
  },

  update(id: string, data: Partial<FileLink>): Promise<FileLink> {
    return api.put(`/filelinks/${id}`, data)
  },

  delete(id: string): Promise<void> {
    return api.delete(`/filelinks/${id}`)
  },

  browse(id: string, subpath?: string): Promise<FileEntry[]> {
    return api.get(`/filelinks/${id}/browse`, { params: subpath ? { subpath } : undefined })
  },

  preview(id: string, subpath: string): Promise<{ content: string }> {
    return api.get(`/filelinks/${id}/preview`, { params: { subpath } })
  },
}
