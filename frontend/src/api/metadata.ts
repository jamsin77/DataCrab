import api from './index'

export interface MetadataEntry {
  id: string
  data_source_id: string
  data_source_name?: string
  table_name: string
  business_name?: string
  business_description?: string
  business_tags?: string[]
  business_purpose?: string
  source_system?: string
  data_domain?: string
  data_owner?: string
  security_level?: string
  column_count?: number
  row_count?: number
  created_at: string
  updated_at?: string
}

export interface MetadataStats {
  total_tables: number
  synced_sources: number
  enriched_tables: number
  tagged_tables: number
}

export const metadataApi = {
  list(dataSourceId?: string, q?: string): Promise<MetadataEntry[]> {
    return api.get('/metadata', { params: { data_source_id: dataSourceId, q } })
  },

  getStats(): Promise<MetadataStats> {
    return api.get('/metadata/stats')
  },

  update(id: string, data: Partial<MetadataEntry>): Promise<MetadataEntry> {
    return api.put(`/metadata/${id}`, data)
  },

  aiEnrich(id: string): Promise<MetadataEntry> {
    return api.post(`/metadata/${id}/ai-enrich`, null, { timeout: 120000 })
  },

  syncDataSource(id: string): Promise<any> {
    return api.post(`/metadata/datasources/${id}/sync`, null, { timeout: 120000 })
  },
}
