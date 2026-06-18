<template>
  <div class="schedule-page">
    <!-- 统计卡片 -->
    <div class="stats-row">
      <el-card class="stat-card">
        <div class="stat-content">
          <div class="stat-value">{{ stats.total_schedules || 0 }}</div>
          <div class="stat-label">总调度</div>
        </div>
      </el-card>
      <el-card class="stat-card">
        <div class="stat-content">
          <div class="stat-value success">{{ stats.active || 0 }}</div>
          <div class="stat-label">运行中</div>
        </div>
      </el-card>
      <el-card class="stat-card">
        <div class="stat-content">
          <div class="stat-value warning">{{ stats.paused || 0 }}</div>
          <div class="stat-label">已暂停</div>
        </div>
      </el-card>
      <el-card class="stat-card">
        <div class="stat-content">
          <div class="stat-value">{{ stats.today_executions || 0 }}</div>
          <div class="stat-label">今日执行</div>
        </div>
      </el-card>
      <el-card class="stat-card">
        <div class="stat-content">
          <div class="stat-value success">{{ stats.success || 0 }}</div>
          <div class="stat-label">成功</div>
        </div>
        <div class="stat-content">
          <div class="stat-value danger">{{ stats.failed || 0 }}</div>
          <div class="stat-label">失败</div>
        </div>
      </el-card>
    </div>

    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <el-button type="primary" @click="openCreateDialog">
          <el-icon><Plus /></el-icon> 新建调度
        </el-button>
      </div>
      <div class="toolbar-right">
        <el-select v-model="filterStatus" placeholder="状态筛选" clearable style="width: 120px">
          <el-option label="运行中" value="active" />
          <el-option label="已暂停" value="paused" />
          <el-option label="已停止" value="stopped" />
        </el-select>
        <el-select v-model="filterTaskType" placeholder="任务类型" clearable style="width: 120px">
          <el-option label="算子" value="operator" />
          <el-option label="技能" value="skill" />
          <el-option label="流程" value="workflow" />
        </el-select>
      </div>
    </div>

    <!-- 调度列表 -->
    <el-table :data="filteredSchedules" stripe style="width: 100%">
      <el-table-column prop="name" label="名称" min-width="150">
        <template #default="{ row }">
          <div class="schedule-name">
            <span>{{ row.name }}</span>
            <el-tag v-if="row.description" size="small" type="info" style="margin-left: 8px">
              {{ row.description }}
            </el-tag>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="task_type" label="任务类型" width="100">
        <template #default="{ row }">
          <el-tag :type="taskTypeColor(row.task_type)" size="small">
            {{ taskTypeLabel(row.task_type) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="schedule_type" label="调度方式" width="120">
        <template #default="{ row }">
          <span v-if="row.schedule_type === 'cron'">
            <el-icon><Clock /></el-icon> Cron
          </span>
          <span v-else-if="row.schedule_type === 'interval'">
            <el-icon><Refresh /></el-icon> 间隔
          </span>
          <span v-else>
            <el-icon><Pointer /></el-icon> 手动
          </span>
        </template>
      </el-table-column>
      <el-table-column label="调度配置" width="180">
        <template #default="{ row }">
          <div v-if="row.schedule_type === 'cron'" class="cron-cell">
            <code>{{ row.cron_expression }}</code>
          </div>
          <div v-else-if="row.schedule_type === 'interval'">
            每 {{ formatInterval(row.interval_seconds) }}
          </div>
          <div v-else>-</div>
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusColor(row.status)" size="small">
            {{ statusLabel(row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="下次执行" width="160">
        <template #default="{ row }">
          <span v-if="row.next_run_at && row.status === 'active'">
            {{ formatTime(row.next_run_at) }}
          </span>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column label="上次执行" width="100">
        <template #default="{ row }">
          <el-tag v-if="row.last_run_status" :type="runStatusColor(row.last_run_status)" size="small">
            {{ row.last_run_status }}
          </el-tag>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="280" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="success" @click="triggerNow(row)">
            <el-icon><CaretRight /></el-icon> 执行
          </el-button>
          <el-button v-if="row.status === 'active'" size="small" @click="pauseSchedule(row.id)">
            <el-icon><VideoPause /></el-icon> 暂停
          </el-button>
          <el-button v-if="row.status === 'paused'" size="small" type="primary" @click="resumeSchedule(row.id)">
            <el-icon><VideoPlay /></el-icon> 恢复
          </el-button>
          <el-button size="small" @click="viewExecutions(row)">
            <el-icon><Document /></el-icon> 历史
          </el-button>
          <el-button size="small" @click="openEditDialog(row)">
            <el-icon><Edit /></el-icon>
          </el-button>
          <el-button size="small" type="danger" @click="deleteSchedule(row.id)">
            <el-icon><Delete /></el-icon>
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 创建/编辑对话框 -->
    <el-dialog v-model="showCreateDialog" :title="editMode ? '编辑调度' : '新建调度'" width="650px" destroy-on-close>
      <el-form :model="createForm" label-width="120px" :rules="formRules" ref="formRef">
        <el-form-item label="调度名称" prop="name">
          <el-input v-model="createForm.name" placeholder="例如：每日数据同步" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="createForm.description" type="textarea" :rows="2" placeholder="调度说明" />
        </el-form-item>
        
        <el-divider content-position="left">任务配置</el-divider>
        
        <el-form-item label="任务类型" prop="task_type">
          <el-radio-group v-model="createForm.task_type" @change="onTaskTypeChange">
            <el-radio-button label="operator">算子</el-radio-button>
            <el-radio-button label="skill">技能</el-radio-button>
            <el-radio-button label="workflow">流程</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="选择任务" prop="task_target_id">
          <el-select v-model="createForm.task_target_id" placeholder="选择要执行的任务" style="width: 100%">
            <el-option
              v-for="item in taskOptions"
              :key="item.id"
              :label="item.name"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="执行参数">
          <el-input
            v-model="createForm.task_params_str"
            type="textarea"
            :rows="3"
            placeholder='JSON格式参数，例如：{"limit": 100}'
          />
        </el-form-item>
        
        <el-divider content-position="left">调度配置</el-divider>
        
        <el-form-item label="调度方式" prop="schedule_type">
          <el-radio-group v-model="createForm.schedule_type">
            <el-radio-button label="cron">Cron表达式</el-radio-button>
            <el-radio-button label="interval">固定间隔</el-radio-button>
            <el-radio-button label="manual">手动触发</el-radio-button>
          </el-radio-group>
        </el-form-item>
        
        <!-- Cron配置 -->
        <template v-if="createForm.schedule_type === 'cron'">
          <el-form-item label="Cron表达式" prop="cron_expression">
            <el-input v-model="createForm.cron_expression" placeholder="0 0 * * *" @blur="validateCron">
              <template #append>
                <el-button @click="showCronHelper = true">助手</el-button>
              </template>
            </el-input>
          </el-form-item>
          <el-form-item v-if="cronValidation" label="">
            <el-alert
              :type="cronValidation.valid ? 'success' : 'error'"
              :closable="false"
              show-icon
            >
              <template #title>
                <span v-if="cronValidation.valid">
                  下次执行: {{ cronValidation.next_runs?.[0] ? formatTime(cronValidation.next_runs[0]) : '-' }}
                </span>
                <span v-else>{{ cronValidation.message }}</span>
              </template>
            </el-alert>
          </el-form-item>
          <el-form-item label="时区">
            <el-select v-model="createForm.timezone" style="width: 100%">
              <el-option label="Asia/Shanghai (北京时间)" value="Asia/Shanghai" />
              <el-option label="UTC" value="UTC" />
              <el-option label="America/New_York" value="America/New_York" />
            </el-select>
          </el-form-item>
        </template>
        
        <!-- 间隔配置 -->
        <template v-if="createForm.schedule_type === 'interval'">
          <el-form-item label="执行间隔" prop="interval_seconds">
            <el-input-number v-model="createForm.interval_value" :min="1" style="width: 150px" />
            <el-select v-model="createForm.interval_unit" style="width: 120px; margin-left: 8px">
              <el-option label="秒" value="seconds" />
              <el-option label="分钟" value="minutes" />
              <el-option label="小时" value="hours" />
              <el-option label="天" value="days" />
            </el-select>
          </el-form-item>
        </template>
        
        <el-divider content-position="left">执行配置</el-divider>
        
        <el-form-item label="最大重试次数">
          <el-input-number v-model="createForm.max_retries" :min="0" :max="10" />
        </el-form-item>
        <el-form-item label="重试间隔(秒)">
          <el-input-number v-model="createForm.retry_interval" :min="10" :max="3600" />
        </el-form-item>
        <el-form-item label="超时时间(秒)">
          <el-input-number v-model="createForm.timeout" :min="60" :max="86400" />
        </el-form-item>
        <el-form-item label="并发数">
          <el-input-number v-model="createForm.concurrent_runs" :min="1" :max="10" />
        </el-form-item>
      </el-form>
      
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="saveSchedule" :loading="saving">
          {{ editMode ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- Cron助手对话框 -->
    <el-dialog v-model="showCronHelper" title="Cron表达式助手" width="600px">
      <div class="cron-helper">
        <el-alert type="info" :closable="false" style="margin-bottom: 16px">
          <template #title>
            Cron表达式格式: 秒 分 时 日 月 周 (支持6位或5位)
          </template>
        </el-alert>
        
        <div class="cron-presets">
          <div class="preset-title">常用预设:</div>
          <el-button v-for="preset in cronPresets" :key="preset.expr" size="small" @click="applyCronPreset(preset.expr)">
            {{ preset.label }}
          </el-button>
        </div>
        
        <div class="cron-examples">
          <div class="example-title">示例:</div>
          <div v-for="ex in cronExamples" :key="ex.expr" class="example-item">
            <code>{{ ex.expr }}</code>
            <span class="example-desc">{{ ex.desc }}</span>
          </div>
        </div>
      </div>
    </el-dialog>

    <!-- 执行历史对话框 -->
    <el-dialog v-model="showExecutionsDialog" :title="`${currentSchedule?.name || ''} - 执行历史`" width="900px">
      <el-table :data="executions" stripe max-height="500">
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="runStatusColor(row.status)" size="small">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="触发方式" width="100">
          <template #default="{ row }">
            {{ row.trigger_type === 'manual' ? '手动' : '自动' }}
          </template>
        </el-table-column>
        <el-table-column label="开始时间" width="160">
          <template #default="{ row }">
            {{ row.started_at ? formatTime(row.started_at) : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="结束时间" width="160">
          <template #default="{ row }">
            {{ row.finished_at ? formatTime(row.finished_at) : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="100">
          <template #default="{ row }">
            {{ row.duration ? `${row.duration}秒` : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="重试" width="80">
          <template #default="{ row }">
            {{ row.retry_count || 0 }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button size="small" @click="viewExecutionDetail(row)">详情</el-button>
            <el-button v-if="row.status === 'failed'" size="small" type="warning">重试</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- 执行详情对话框 -->
    <el-dialog v-model="showExecutionDetail" title="执行详情" width="800px">
      <div v-if="executionDetail" class="execution-detail">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="状态">
            <el-tag :type="runStatusColor(executionDetail.status)">
              {{ executionDetail.status }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="触发方式">
            {{ executionDetail.trigger_type === 'manual' ? '手动' : '自动' }}
          </el-descriptions-item>
          <el-descriptions-item label="开始时间">
            {{ executionDetail.started_at ? formatTime(executionDetail.started_at) : '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="结束时间">
            {{ executionDetail.finished_at ? formatTime(executionDetail.finished_at) : '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="耗时">
            {{ executionDetail.duration ? `${executionDetail.duration}秒` : '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="重试次数">
            {{ executionDetail.retry_count || 0 }}
          </el-descriptions-item>
        </el-descriptions>
        
        <div v-if="executionDetail.error_message" style="margin-top: 16px">
          <div class="detail-label">错误信息:</div>
          <el-alert type="error" :closable="false">
            <pre>{{ executionDetail.error_message }}</pre>
          </el-alert>
        </div>
        
        <div v-if="executionDetail.logs" style="margin-top: 16px">
          <div class="detail-label">执行日志:</div>
          <pre class="log-content">{{ executionDetail.logs }}</pre>
        </div>
        
        <div v-if="executionDetail.result" style="margin-top: 16px">
          <div class="detail-label">执行结果:</div>
          <pre class="result-content">{{ JSON.stringify(executionDetail.result, null, 2) }}</pre>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import api from '@/api/index'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

const schedules = ref<any[]>([])
const stats = ref<any>({})
const operators = ref<any[]>([])
const skills = ref<any[]>([])

const filterStatus = ref('')
const filterTaskType = ref('')
const showCreateDialog = ref(false)
const showCronHelper = ref(false)
const showExecutionsDialog = ref(false)
const showExecutionDetail = ref(false)
const editMode = ref(false)
const saving = ref(false)
const formRef = ref<FormInstance>()
const cronValidation = ref<any>(null)
const currentSchedule = ref<any>(null)
const executions = ref<any[]>([])
const executionDetail = ref<any>(null)

const createForm = ref({
  name: '',
  description: '',
  task_type: 'operator',
  task_target_id: '',
  task_params_str: '',
  schedule_type: 'cron',
  cron_expression: '',
  timezone: 'Asia/Shanghai',
  interval_value: 1,
  interval_unit: 'hours',
  interval_seconds: 3600,
  max_retries: 3,
  retry_interval: 60,
  timeout: 3600,
  concurrent_runs: 1,
})

const formRules: FormRules = {
  name: [{ required: true, message: '请输入调度名称', trigger: 'blur' }],
  task_type: [{ required: true, message: '请选择任务类型', trigger: 'change' }],
  task_target_id: [{ required: true, message: '请选择任务', trigger: 'change' }],
  schedule_type: [{ required: true, message: '请选择调度方式', trigger: 'change' }],
  cron_expression: [
    { required: true, message: '请输入Cron表达式', trigger: 'blur' },
  ],
}

const cronPresets = [
  { label: '每分钟', expr: '*/1 * * * *' },
  { label: '每小时', expr: '0 * * * *' },
  { label: '每天零点', expr: '0 0 * * *' },
  { label: '每天8点', expr: '0 8 * * *' },
  { label: '每周一8点', expr: '0 8 * * 1' },
  { label: '每月1号', expr: '0 0 1 * *' },
]

const cronExamples = [
  { expr: '0 0 * * *', desc: '每天零点执行' },
  { expr: '0 */2 * * *', desc: '每2小时执行' },
  { expr: '0 9-17 * * 1-5', desc: '工作日9-17点每小时执行' },
  { expr: '30 4 * * 6,0', desc: '周末4:30执行' },
  { expr: '0 0 1 */3 *', desc: '每季度首日执行' },
]

const filteredSchedules = computed(() => {
  let list = schedules.value
  if (filterStatus.value) {
    list = list.filter(s => s.status === filterStatus.value)
  }
  if (filterTaskType.value) {
    list = list.filter(s => s.task_type === filterTaskType.value)
  }
  return list
})

const taskOptions = computed(() => {
  if (createForm.value.task_type === 'operator') {
    return operators.value.map(o => ({ id: o.id, name: o.display_name || o.name }))
  } else if (createForm.value.task_type === 'skill') {
    return skills.value.map(s => ({ id: s.id, name: s.display_name || s.name }))
  }
  return []
})

onMounted(async () => {
  await Promise.all([
    loadSchedules(),
    loadStats(),
    loadOperators(),
    loadSkills(),
  ])
})

async function loadSchedules() {
  try {
    // 检查是否已登录
    const token = localStorage.getItem('access_token')
    if (!token) {
      ElMessage.warning('请先登录')
      return
    }
    
    schedules.value = await api.get('/schedules')
  } catch (e: any) {
    console.error('加载调度列表失败:', e)
    const errorMsg = e.response?.data?.detail || e.message || '未知错误'
    if (e.response?.status === 401) {
      ElMessage.error('登录已过期，请重新登录')
    } else {
      ElMessage.error(`加载调度列表失败: ${errorMsg}`)
    }
  }
}

async function loadStats() {
  try {
    stats.value = await api.get('/schedules/stats/overview')
  } catch (e: any) {
    // ignore
  }
}

async function loadOperators() {
  try {
    operators.value = await api.get('/operators')
  } catch (e: any) {
    // ignore
  }
}

async function loadSkills() {
  try {
    skills.value = await api.get('/skills')
  } catch (e: any) {
    // ignore
  }
}

function openCreateDialog() {
  editMode.value = false
  createForm.value = {
    name: '',
    description: '',
    task_type: 'operator',
    task_target_id: '',
    task_params_str: '',
    schedule_type: 'cron',
    cron_expression: '',
    timezone: 'Asia/Shanghai',
    interval_value: 1,
    interval_unit: 'hours',
    interval_seconds: 3600,
    max_retries: 3,
    retry_interval: 60,
    timeout: 3600,
    concurrent_runs: 1,
  }
  cronValidation.value = null
  showCreateDialog.value = true
}

function openEditDialog(schedule: any) {
  editMode.value = true
  currentSchedule.value = schedule
  createForm.value = {
    name: schedule.name,
    description: schedule.description || '',
    task_type: schedule.task_type,
    task_target_id: schedule.task_target_id,
    task_params_str: schedule.task_params ? JSON.stringify(schedule.task_params, null, 2) : '',
    schedule_type: schedule.schedule_type,
    cron_expression: schedule.cron_expression || '',
    timezone: schedule.timezone || 'Asia/Shanghai',
    interval_value: 1,
    interval_unit: 'hours',
    interval_seconds: schedule.interval_seconds || 3600,
    max_retries: schedule.max_retries || 3,
    retry_interval: schedule.retry_interval || 60,
    timeout: schedule.timeout || 3600,
    concurrent_runs: schedule.concurrent_runs || 1,
  }
  showCreateDialog.value = true
}

function onTaskTypeChange() {
  createForm.value.task_target_id = ''
}

async function validateCron() {
  if (!createForm.value.cron_expression) return
  try {
    cronValidation.value = await api.post('/schedules/validate-cron', {
      cron_expression: createForm.value.cron_expression,
    })
  } catch (e: any) {
    cronValidation.value = { valid: false, message: '验证失败' }
  }
}

function applyCronPreset(expr: string) {
  createForm.value.cron_expression = expr
  showCronHelper.value = false
  validateCron()
}

async function saveSchedule() {
  if (!formRef.value) return
  await formRef.value.validate()
  
  saving.value = true
  try {
    // 计算间隔秒数
    let intervalSeconds = createForm.value.interval_seconds
    if (createForm.value.schedule_type === 'interval') {
      const multipliers: any = { seconds: 1, minutes: 60, hours: 3600, days: 86400 }
      intervalSeconds = createForm.value.interval_value * multipliers[createForm.value.interval_unit]
    }
    
    // 解析参数
    let taskParams = null
    if (createForm.value.task_params_str) {
      try {
        taskParams = JSON.parse(createForm.value.task_params_str)
      } catch {
        ElMessage.error('参数JSON格式错误')
        saving.value = false
        return
      }
    }
    
    const data: any = {
      name: createForm.value.name,
      description: createForm.value.description,
      task_type: createForm.value.task_type,
      task_target_id: createForm.value.task_target_id,
      task_params: taskParams,
      schedule_type: createForm.value.schedule_type,
      cron_expression: createForm.value.cron_expression || null,
      timezone: createForm.value.timezone,
      interval_seconds: intervalSeconds,
      max_retries: createForm.value.max_retries,
      retry_interval: createForm.value.retry_interval,
      timeout: createForm.value.timeout,
      concurrent_runs: createForm.value.concurrent_runs,
    }
    
    if (editMode.value && currentSchedule.value) {
      await api.put(`/schedules/${currentSchedule.value.id}`, data)
      ElMessage.success('更新成功')
    } else {
      await api.post('/schedules', data)
      ElMessage.success('创建成功')
    }
    
    showCreateDialog.value = false
    await loadSchedules()
    await loadStats()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  } finally {
    saving.value = false
  }
}

async function pauseSchedule(id: string) {
  try {
    await api.post(`/schedules/${id}/pause`)
    ElMessage.success('已暂停')
    await loadSchedules()
    await loadStats()
  } catch (e: any) {
    ElMessage.error('操作失败')
  }
}

async function resumeSchedule(id: string) {
  try {
    await api.post(`/schedules/${id}/resume`)
    ElMessage.success('已恢复')
    await loadSchedules()
    await loadStats()
  } catch (e: any) {
    ElMessage.error('操作失败')
  }
}

async function triggerNow(schedule: any) {
  try {
    await ElMessageBox.confirm(
      `确定要立即执行调度"${schedule.name}"吗？`,
      '确认执行',
      { type: 'warning' }
    )
    const result = await api.post(`/schedules/${schedule.id}/trigger`)
    ElMessage.success('任务已触发，正在执行中...')
    await loadSchedules()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e.response?.data?.detail || '执行失败')
    }
  }
}

async function deleteSchedule(id: string) {
  try {
    await ElMessageBox.confirm('确定要删除此调度吗？', '确认删除', { type: 'warning' })
    await api.delete(`/schedules/${id}`)
    ElMessage.success('删除成功')
    await loadSchedules()
    await loadStats()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

async function viewExecutions(schedule: any) {
  currentSchedule.value = schedule
  try {
    executions.value = await api.get(`/schedules/${schedule.id}/executions`)
    showExecutionsDialog.value = true
  } catch (e: any) {
    ElMessage.error('加载执行历史失败')
  }
}

async function viewExecutionDetail(exec: any) {
  try {
    executionDetail.value = await api.get(`/schedules/executions/${exec.id}`)
    showExecutionDetail.value = true
  } catch (e: any) {
    ElMessage.error('加载详情失败')
  }
}

function taskTypeLabel(type: string) {
  const map: any = { operator: '算子', skill: '技能', workflow: '流程' }
  return map[type] || type
}

function taskTypeColor(type: string) {
  const map: any = { operator: 'primary', skill: 'success', workflow: 'warning' }
  return map[type] || ''
}

function statusLabel(status: string) {
  const map: any = { active: '运行中', paused: '已暂停', stopped: '已停止' }
  return map[status] || status
}

function statusColor(status: string) {
  const map: any = { active: 'success', paused: 'warning', stopped: 'info' }
  return map[status] || ''
}

function runStatusColor(status: string) {
  const map: any = { pending: 'info', running: 'primary', success: 'success', failed: 'danger', timeout: 'warning' }
  return map[status] || ''
}

function formatTime(time: string) {
  return new Date(time).toLocaleString('zh-CN')
}

function formatInterval(seconds: number) {
  if (seconds < 60) return `${seconds}秒`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}分钟`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}小时`
  return `${Math.floor(seconds / 86400)}天`
}
</script>

<style lang="scss" scoped>
.schedule-page {
  padding: 20px;
  background: #f5f7fa;
  min-height: calc(100vh - 60px);
}

.stats-row {
  display: flex;
  gap: 16px;
  margin-bottom: 20px;
  
  .stat-card {
    flex: 1;
    
    .stat-content {
      text-align: center;
      
      .stat-value {
        font-size: 28px;
        font-weight: bold;
        color: #409eff;
        
        &.success { color: #67c23a; }
        &.warning { color: #e6a23c; }
        &.danger { color: #f56c6c; }
      }
      
      .stat-label {
        font-size: 14px;
        color: #909399;
        margin-top: 4px;
      }
    }
  }
}

.toolbar {
  background: #fff;
  padding: 16px;
  border-radius: 8px;
  margin-bottom: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  
  .toolbar-left {
    display: flex;
    gap: 12px;
    align-items: center;
  }
  
  .toolbar-right {
    display: flex;
    gap: 12px;
    align-items: center;
  }
}

.schedule-name {
  display: flex;
  align-items: center;
}

.cron-cell {
  code {
    background: #f5f7fa;
    padding: 2px 8px;
    border-radius: 4px;
    font-family: monospace;
  }
}

.cron-helper {
  .cron-presets, .cron-examples {
    margin-bottom: 16px;
    
    .preset-title, .example-title {
      font-weight: bold;
      margin-bottom: 8px;
    }
  }
  
  .cron-presets {
    .el-button {
      margin-right: 8px;
      margin-bottom: 8px;
    }
  }
  
  .example-item {
    margin-bottom: 8px;
    
    code {
      background: #f5f7fa;
      padding: 2px 8px;
      border-radius: 4px;
      margin-right: 12px;
    }
    
    .example-desc {
      color: #909399;
    }
  }
}

.execution-detail {
  .detail-label {
    font-weight: bold;
    margin-bottom: 8px;
  }
  
  .log-content, .result-content {
    background: #f5f7fa;
    padding: 12px;
    border-radius: 4px;
    max-height: 300px;
    overflow: auto;
    font-family: monospace;
    font-size: 13px;
  }
}
</style>
