import api from './index'

export interface KbDocument {
  id: string
  name: string
  file_type: string
  size_bytes: number
  chunk_count: number
  status: string
  error?: string
  created_at: string
}

export interface KbSearchResult {
  chroma_id: string
  content: string
  document_id: string
  doc_name: string
  chunk_index: number
  location: string
  score: number | null
}

export const knowledgeApi = {
  listDocuments(): Promise<KbDocument[]> {
    return api.get('/knowledge/documents')
  },

  upload(file: File): Promise<KbDocument> {
    const form = new FormData()
    form.append('file', file)
    return api.post('/knowledge/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
    })
  },

  deleteDocument(id: string): Promise<void> {
    return api.delete(`/knowledge/documents/${id}`)
  },

  getChunks(id: string): Promise<any[]> {
    return api.get(`/knowledge/documents/${id}/chunks`)
  },

  search(query: string, topK = 5): Promise<{ query: string; results: KbSearchResult[] }> {
    return api.post('/knowledge/search', { query, top_k: topK })
  },
}
