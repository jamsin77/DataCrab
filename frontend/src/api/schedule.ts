import api from './index'

export interface Schedule {
  id: string
  name: string
  description?: string
  task_type: string
  task_target_id: string
  task_params?: Record<string, any>
  schedule_type: string
  cron_expression?: string
  timezone?: string
  interval_seconds?: number
  max_retries: number
  retry_interval: number
  timeout?: number
  concurrent_runs: number
  is_active: boolean
  created_at: string
  updated_at?: string
}

export interface ScheduleStats {
  total: number
  active: number
  paused: number
  today_executions: number
  success_count: number
  failed_count: number
}

export interface ScheduleExecution {
  id: string
  schedule_id: string
  status: string
  result?: any
  error_message?: string
  started_at: string
  completed_at?: string
}

export const scheduleApi = {
  list(): Promise<Schedule[]> {
    return api.get('/schedules')
  },

  getStats(): Promise<ScheduleStats> {
    return api.get('/schedules/stats/overview')
  },

  validateCron(cronExpression: string): Promise<{ valid: boolean; message?: string }> {
    return api.post('/schedules/validate-cron', { cron_expression: cronExpression })
  },

  create(data: Partial<Schedule>): Promise<Schedule> {
    return api.post('/schedules', data)
  },

  update(id: string, data: Partial<Schedule>): Promise<Schedule> {
    return api.put(`/schedules/${id}`, data)
  },

  pause(id: string): Promise<Schedule> {
    return api.post(`/schedules/${id}/pause`)
  },

  resume(id: string): Promise<Schedule> {
    return api.post(`/schedules/${id}/resume`)
  },

  trigger(id: string): Promise<ScheduleExecution> {
    return api.post(`/schedules/${id}/trigger`)
  },

  delete(id: string): Promise<void> {
    return api.delete(`/schedules/${id}`)
  },

  getExecutions(id: string): Promise<ScheduleExecution[]> {
    return api.get(`/schedules/${id}/executions`)
  },

  getExecution(executionId: string): Promise<ScheduleExecution> {
    return api.get(`/schedules/executions/${executionId}`)
  },
}
