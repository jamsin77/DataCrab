import api from './index'

export interface Workflow {
  id: string
  name: string
  description?: string
  nodes?: any[]
  edges?: any[]
  engine?: string
  created_by?: string
  created_at: string
  updated_at?: string
}

export interface WorkflowExecution {
  id: string
  workflow_id: string
  status: string
  result?: any
  started_at: string
  completed_at?: string
}

export interface WorkflowValidationResult {
  valid: boolean
  errors?: string[]
  warnings?: string[]
}

export const workflowApi = {
  list(): Promise<Workflow[]> {
    return api.get('/workflows')
  },

  get(id: string): Promise<Workflow> {
    return api.get(`/workflows/${id}`)
  },

  create(data: Partial<Workflow>): Promise<Workflow> {
    return api.post('/workflows', data)
  },

  update(id: string, data: Partial<Workflow>): Promise<Workflow> {
    return api.put(`/workflows/${id}`, data)
  },

  delete(id: string): Promise<void> {
    return api.delete(`/workflows/${id}`)
  },

  fromSkill(skillId: string): Promise<Workflow> {
    return api.post(`/workflows/from-skill/${skillId}`)
  },

  validate(id: string): Promise<WorkflowValidationResult> {
    return api.post(`/workflows/${id}/validate`)
  },

  run(id: string, inputs?: Record<string, any>): Promise<WorkflowExecution> {
    return api.post(`/workflows/${id}/run`, { inputs })
  },

  getExecutions(id: string): Promise<WorkflowExecution[]> {
    return api.get(`/workflows/${id}/executions`)
  },

  getExecution(executionId: string): Promise<WorkflowExecution> {
    return api.get(`/workflows/executions/${executionId}`)
  },

  clone(id: string): Promise<Workflow> {
    return api.post(`/workflows/${id}/clone`)
  },

  getEngines(): Promise<string[]> {
    return api.get('/workflows/engines')
  },
}
