import api from './index'

export interface Pipeline {
  id: string
  name: string
  display_name?: string
  description?: string
  main_code?: string
  skill_calls?: any[]
  created_by?: string
  created_at: string
  updated_at?: string
}

export interface PipelineExecution {
  id: string
  pipeline_id: string
  status: string
  result?: any
  started_at: string
  completed_at?: string
}

export const pipelineApi = {
  list(search?: string): Promise<Pipeline[]> {
    return api.get('/pipelines', { params: search ? { search } : undefined })
  },

  get(id: string): Promise<Pipeline> {
    return api.get(`/pipelines/${id}`)
  },

  fromSkill(skillId: string): Promise<Pipeline> {
    return api.post(`/pipelines/from-skill/${skillId}`)
  },

  run(id: string, inputs?: Record<string, any>): Promise<PipelineExecution> {
    return api.post(`/pipelines/${id}/run`, { inputs: inputs || {} })
  },

  clone(id: string): Promise<Pipeline> {
    return api.post(`/pipelines/${id}/clone`)
  },

  delete(id: string): Promise<void> {
    return api.delete(`/pipelines/${id}`)
  },

  getExecutions(id: string, limit = 20): Promise<PipelineExecution[]> {
    return api.get(`/pipelines/${id}/executions`, { params: { limit } })
  },
}
