import api from './index'

export interface Skill {
  id: string
  name: string
  display_name: string
  category: string
  version: number
  visibility: string
  skill_path: string
  skill_md: string
  scripts: SkillScript[]
  usage_count: number
  created_by?: string
  created_at: string
  updated_at?: string
}

export interface SkillScript {
  name: string
  size?: number
  content?: string
}

export interface SkillParam {
  name: string
  type: string
  default?: any
  description?: string
  is_datasource?: boolean
  is_table?: boolean
  is_list?: boolean
  required?: boolean
}

export const skillApi = {
  list(limit = 100): Promise<Skill[]> {
    return api.get('/skills', { params: { limit } })
  },

  get(id: string): Promise<Skill> {
    return api.get(`/skills/${id}`)
  },

  delete(id: string): Promise<void> {
    return api.delete(`/skills/${id}`)
  },

  getParams(id: string): Promise<SkillParam[]> {
    return api.get(`/skills/${id}/params`)
  },

  getScripts(id: string): Promise<SkillScript[]> {
    return api.get(`/skills/${id}/scripts`)
  },

  updateScript(id: string, scriptName: string, content: string): Promise<any> {
    return api.put(`/skills/${id}/scripts/${scriptName}`, { content })
  },

  generate(data: { prompt: string }, timeout = 120000): Promise<Skill> {
    return api.post('/skills/generate', data, { timeout })
  },
}
