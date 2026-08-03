<template>
  <div class="schedule-page">
    <div class="toolbar">
      <el-button type="primary" @click="openCreateDialog">
        <el-icon><Plus /></el-icon> 新建调度
      </el-button>
      <el-select v-model="filterStatus" placeholder="状态" clearable style="width: 130px">
        <el-option label="运行中" value="active" />
        <el-option label="已暂停" value="paused" />
      </el-select>
    </div>

    <el-table :data="filteredSchedules" stripe style="width: 100%" v-loading="loading">
      <el-table-column label="名称" min-width="150">
        <template #default="{ row }">
          <div>
            {{ row.name }}
            <el-tag v-if="row.is_builtin" size="small" type="warning" effect="dark" style="margin-left: 4px">内置</el-tag>
          </div>
          <div v-if="row.description" class="row-desc">{{ row.description }}</div>
        </template>
      </el-table-column>
      <el-table-column label="流程" min-width="140">
        <template #default="{ row }">{{ pipelineName(row.task_target_id) }}</template>
      </el-table-column>
      <el-table-column label="调度方式" width="120">
        <template #default="{ row }">
          <el-tag v-if="row.schedule_type === 'cron'" size="small">定时</el-tag>
          <el-tag v-else-if="row.schedule_type === 'interval' && row.interval_seconds === 1" size="small" type="danger">永久在线</el-tag>
          <el-tag v-else-if="row.schedule_type === 'interval'" size="small" type="success">周期</el-tag>
          <el-tag v-else size="small" type="info">手动</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="调度配置" width="200">
        <template #default="{ row }">
          <div v-if="row.schedule_type === 'cron'">
            <div>{{ cronToHumanReadable(row.cron_expression) }}</div>
            <div class="row-desc">{{ timezoneLabel(row.timezone) }}</div>
          </div>
          <span v-else-if="row.schedule_type === 'interval' && row.interval_seconds === 1">持续运行</span>
          <span v-else-if="row.schedule_type === 'interval'">{{ formatInterval(row.interval_seconds) }}</span>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column label="运行模式" width="100">
        <template #default="{ row }">
          <el-tag :type="row.run_mode === 'auto_fix' ? 'warning' : 'info'" size="small">
            {{ row.run_mode === 'auto_fix' ? '自修复' : '普通' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'warning'" size="small">
            {{ row.status === 'active' ? '运行中' : '已暂停' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="下次执行" width="160">
        <template #default="{ row }">{{ formatTime(row.next_run_at) }}</template>
      </el-table-column>
      <el-table-column label="上次结果" width="90">
        <template #default="{ row }">
          <el-tag v-if="row.last_run_status === 'success'" type="success" size="small">成功</el-tag>
          <el-tag v-else-if="row.last_run_status === 'failed'" type="danger" size="small">失败</el-tag>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="260" fixed="right">
        <template #default="{ row }">
          <div class="op-btns">
            <el-button size="small" type="primary" @click="triggerNow(row)">执行</el-button>
            <el-button v-if="row.status === 'active'" size="small" @click="pauseSchedule(row)">暂停</el-button>
            <el-button v-else size="small" type="success" @click="resumeSchedule(row)">恢复</el-button>
            <el-button size="small" @click="viewExecutions(row)">历史</el-button>
            <el-button size="small" @click="openEditDialog(row)">编辑</el-button>
            <el-button v-if="!row.is_builtin" size="small" type="danger" plain @click="deleteSchedule(row)">删除</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新建/编辑对话框 -->
    <el-dialog v-model="showDialog" :title="editing ? '编辑调度' : '新建调度'" width="560px">
      <el-form label-width="100px" class="schedule-dialog-form">
        <el-form-item label="调度名称" required>
          <el-input v-model="form.name" placeholder="如：每日数据清洗" :disabled="isBuiltinSchedule" />
        </el-form-item>
        <el-form-item label="选择流程" required>
          <el-select v-model="form.task_target_id" placeholder="选择流程" filterable style="width: 100%" :disabled="isBuiltinSchedule" @change="onPipelineChange">
            <el-option v-for="p in pipelines" :key="p.id" :label="p.display_name || p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="运行模式">
          <el-radio-group v-model="form.run_mode" :disabled="isBuiltinSchedule">
            <el-radio value="normal">普通运行</el-radio>
            <el-radio value="auto_fix">自修复运行</el-radio>
          </el-radio-group>
          <span class="form-hint">{{ isBuiltinSchedule ? '内置调度不允许修改运行模式' : (form.run_mode === 'auto_fix' ? '执行失败时自动修复代码，走双智能体检查' : '直接执行流程脚本') }}</span>
        </el-form-item>
        <el-form-item label="调度方式">
          <el-radio-group v-model="form.schedule_type" :disabled="isBuiltinSchedule">
            <el-radio value="cron">定时</el-radio>
            <el-radio value="interval">周期</el-radio>
            <el-radio value="continuous">永久在线</el-radio>
          </el-radio-group>
          <span v-if="isBuiltinSchedule" class="form-hint">内置调度不允许修改调度方式</span>
        </el-form-item>

        <!-- 定时：可视化选择 -->
        <template v-if="form.schedule_type === 'cron'">
          <el-form-item label="执行时间">
            <div class="cron-times">
              <div v-for="(t, i) in cronTimes" :key="i" class="cron-time-row">
                <el-time-picker v-model="cronTimes[i]" format="HH:mm" value-format="HH:mm" placeholder="输入时间" style="width: 140px" clearable />
                <el-button v-if="cronTimes.length > 1" size="small" text type="danger" @click="cronTimes.splice(i, 1)">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </div>
              <el-button size="small" text type="primary" @click="cronTimes.push('12:00')">
                <el-icon><Plus /></el-icon> 添加时间
              </el-button>
            </div>
          </el-form-item>
          <el-form-item label="时区">
            <el-select v-model="cronTimezone" filterable allow-create default-first-option placeholder="选择时区" style="width: 240px">
              <el-option v-for="tz in commonTimezones" :key="tz" :label="timezoneLabel(tz)" :value="tz" />
            </el-select>
            <span class="form-hint">执行时间按此时区触发（已自动检测浏览器时区，可手动修改）</span>
          </el-form-item>
          <el-form-item label="重复频率">
            <el-select v-model="cronFrequency" style="width: 120px" :disabled="isBuiltinSchedule">
              <el-option label="每天" value="daily" />
              <el-option v-if="!isBuiltinSchedule" label="每周" value="weekly" />
              <el-option v-if="!isBuiltinSchedule" label="每月" value="monthly" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="cronFrequency === 'weekly'" label="星期">
            <el-checkbox-group v-model="cronWeekdays">
              <el-checkbox v-for="(d, i) in ['一','二','三','四','五','六','日']" :key="i" :value="i+1" :label="d">{{ d }}</el-checkbox>
            </el-checkbox-group>
          </el-form-item>
          <el-form-item v-if="cronFrequency === 'monthly'" label="日期">
            <el-input-number v-model="cronMonthDay" :min="1" :max="28" /> 号
          </el-form-item>
          <el-form-item label="预览">
            <el-tag type="info" size="small">{{ cronHumanReadable }}</el-tag>
          </el-form-item>
        </template>

        <!-- 周期 -->
        <el-form-item v-if="form.schedule_type === 'interval'" label="执行间隔">
          <div class="interval-row">
            <el-input-number v-model="intervalValue" :min="1" />
            <el-select v-model="intervalUnit" style="width: 90px">
              <el-option label="秒" :value="1" />
              <el-option label="分钟" :value="60" />
              <el-option label="小时" :value="3600" />
              <el-option label="天" :value="86400" />
            </el-select>
          </div>
        </el-form-item>

        <!-- 永久在线 -->
        <el-form-item v-if="form.schedule_type === 'continuous'" label="说明">
          <span class="form-hint">流程执行完成后自动重新启动，保持持续运行。并发数为 1，不会重叠执行。</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" @click="saveSchedule" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- 执行历史 -->
    <el-dialog v-model="showHistory" title="执行历史" width="800px" @close="stopPolling">
      <template #header>
        <div class="history-header">
          <span>执行历史</span>
          <el-button size="small" text :loading="historyLoading" @click="refreshExecutions">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
        </div>
      </template>
      <el-table :data="executions" stripe>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="execStatusColor(row.status)" size="small">{{ execStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="触发方式" width="80">
          <template #default="{ row }">{{ row.trigger_type === 'manual' ? '手动' : '自动' }}</template>
        </el-table-column>
        <el-table-column label="开始" width="160">
          <template #default="{ row }">{{ formatTime(row.started_at) }}</template>
        </el-table-column>
        <el-table-column label="耗时" width="80">
          <template #default="{ row }">{{ row.duration ? row.duration + 's' : '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button size="small" text @click="viewExecutionDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- 执行详情 -->
    <el-dialog v-model="showDetail" title="执行详情" width="700px" @close="stopDetailPolling">
      <template #header>
        <div class="history-header">
          <span>执行详情</span>
          <el-button size="small" text :loading="detailLoading" @click="refreshExecutionDetail">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
        </div>
      </template>
      <el-descriptions :column="2" border v-if="executionDetail">
        <el-descriptions-item label="状态">{{ execStatusLabel(executionDetail.status) }}</el-descriptions-item>
        <el-descriptions-item label="耗时">{{ executionDetail.duration || 0 }}s</el-descriptions-item>
        <el-descriptions-item label="开始">{{ formatTime(executionDetail.started_at) }}</el-descriptions-item>
        <el-descriptions-item label="结束">{{ formatTime(executionDetail.finished_at) }}</el-descriptions-item>
      </el-descriptions>
      <div v-if="executionDetail?.result" class="detail-result">
        <div class="detail-label">执行结果</div>
        <pre class="result-pre">{{ formatResult(executionDetail.result) }}</pre>
      </div>
      <div v-if="executionDetail?.error_message" class="detail-error">
        <div class="detail-label">错误信息</div>
        <pre class="error-pre">{{ executionDetail.error_message }}</pre>
      </div>
      <div v-if="executionDetail?.logs" class="detail-logs">
        <div class="detail-label">执行日志</div>
        <pre>{{ executionDetail.logs }}</pre>
      </div>
      <div v-else-if="executionDetail" class="detail-logs">
        <div class="detail-label">执行日志</div>
        <el-text type="info" size="small">暂无日志输出（流程脚本未产生 stdout）</el-text>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete, Refresh } from '@element-plus/icons-vue'
import api from '@/api'

interface Schedule {
  id: string
  name: string
  description?: string
  task_type: string
  task_target_id: string
  schedule_type: string
  cron_expression?: string
  timezone?: string
  interval_seconds?: number
  run_mode: string
  status: string
  is_builtin?: boolean
  next_run_at?: string
  last_run_status?: string
  last_run_at?: string
}

const schedules = ref<Schedule[]>([])
const pipelines = ref<any[]>([])
const loading = ref(false)
const saving = ref(false)
const filterStatus = ref('')
const showDialog = ref(false)
const editing = ref(false)
const isBuiltinSchedule = ref(false)
const showHistory = ref(false)
const showDetail = ref(false)
const executions = ref<any[]>([])
const executionDetail = ref<any>(null)
const detailLoading = ref(false)
const currentExecutionId = ref('')
const detailPollTimer = ref<number | null>(null)
const historyLoading = ref(false)
const pollTimer = ref<number | null>(null)
const currentScheduleId = ref('')

const form = ref({
  id: '',
  name: '',
  task_target_id: '',
  schedule_type: 'cron',
  run_mode: 'normal',
})

const intervalValue = ref(5)
const intervalUnit = ref(60)
const cronTimes = ref<string[]>(['08:00'])
const cronFrequency = ref('daily')
const cronWeekdays = ref<number[]>([1])
const cronMonthDay = ref(1)
const detectedTz = (Intl.DateTimeFormat().resolvedOptions().timeZone) || 'UTC'
const cronTimezone = ref(detectedTz)
const commonTimezones = [
  'UTC',
  'Asia/Shanghai', 'Asia/Tokyo', 'Asia/Seoul', 'Asia/Singapore', 'Asia/Hong_Kong',
  'Asia/Bangkok', 'Asia/Kolkata', 'Asia/Dubai', 'Asia/Tehran', 'Asia/Jerusalem',
  'Europe/London', 'Europe/Paris', 'Europe/Berlin', 'Europe/Madrid', 'Europe/Rome',
  'Europe/Moscow', 'Europe/Istanbul', 'Europe/Amsterdam', 'Europe/Stockholm',
  'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles',
  'America/Anchorage', 'America/Toronto', 'America/Mexico_City', 'America/Sao_Paulo',
  'America/Argentina/Buenos_Aires', 'America/Bogota',
  'Australia/Sydney', 'Australia/Perth', 'Pacific/Auckland', 'Pacific/Honolulu',
  'Africa/Cairo', 'Africa/Johannesburg', 'Africa/Lagos', 'Africa/Nairobi',
]
const TZ_LABELS: Record<string, string> = {
  'UTC': 'UTC 协调世界时',
  'Asia/Shanghai': '中国 北京',
  'Asia/Hong_Kong': '中国 香港',
  'Asia/Tokyo': '日本 东京',
  'Asia/Seoul': '韩国 首尔',
  'Asia/Singapore': '新加坡',
  'Asia/Bangkok': '泰国 曼谷',
  'Asia/Kolkata': '印度 加尔各答',
  'Asia/Dubai': '阿联酋 迪拜',
  'Asia/Tehran': '伊朗 德黑兰',
  'Asia/Jerusalem': '以色列 耶路撒冷',
  'Europe/London': '英国 伦敦',
  'Europe/Paris': '法国 巴黎',
  'Europe/Berlin': '德国 柏林',
  'Europe/Madrid': '西班牙 马德里',
  'Europe/Rome': '意大利 罗马',
  'Europe/Moscow': '俄罗斯 莫斯科',
  'Europe/Istanbul': '土耳其 伊斯坦布尔',
  'Europe/Amsterdam': '荷兰 阿姆斯特丹',
  'Europe/Stockholm': '瑞典 斯德哥尔摩',
  'America/New_York': '美国 纽约',
  'America/Chicago': '美国 芝加哥',
  'America/Denver': '美国 丹佛',
  'America/Los_Angeles': '美国 洛杉矶',
  'America/Anchorage': '美国 安克雷奇',
  'America/Toronto': '加拿大 多伦多',
  'America/Mexico_City': '墨西哥 墨西哥城',
  'America/Sao_Paulo': '巴西 圣保罗',
  'America/Argentina/Buenos_Aires': '阿根廷 布宜诺斯艾利斯',
  'America/Bogota': '哥伦比亚 波哥大',
  'Australia/Sydney': '澳大利亚 悉尼',
  'Australia/Perth': '澳大利亚 珀斯',
  'Pacific/Auckland': '新西兰 奥克兰',
  'Pacific/Honolulu': '美国 檀香山',
  'Africa/Cairo': '埃及 开罗',
  'Africa/Johannesburg': '南非 约翰内斯堡',
  'Africa/Lagos': '尼日利亚 拉各斯',
  'Africa/Nairobi': '肯尼亚 内罗毕',
}
function timezoneLabel(tz?: string): string {
  if (!tz) return 'UTC'
  return TZ_LABELS[tz] || tz
}

const cronHumanReadable = computed(() => {
  const times = cronTimes.value.filter(t => t).map(t => {
    const [h, m] = t.split(':')
    return `${h.padStart(2,'0')}:${m.padStart(2,'0')}`
  })
  if (!times.length) return ''
  const tz = `（${timezoneLabel(cronTimezone.value)}）`
  const timeStr = times.join('、')
  if (cronFrequency.value === 'daily') return `每天 ${timeStr}${tz}`
  if (cronFrequency.value === 'weekly') {
    const names = ['一','二','三','四','五','六','日']
    const days = cronWeekdays.value.map(d => '周' + names[d-1]).join('、')
    return `每${days} ${timeStr}${tz}`
  }
  if (cronFrequency.value === 'monthly') return `每月${cronMonthDay.value}号 ${timeStr}${tz}`
  return ''
})

function buildCronExpression(): string {
  const exprs = cronTimes.value.filter(t => t).map(t => {
    const [h, m] = t.split(':')
    if (cronFrequency.value === 'daily') return `${m} ${h} * * *`
    if (cronFrequency.value === 'weekly') {
      const days = cronWeekdays.value.length ? cronWeekdays.value.sort().join(',') : '*'
      return `${m} ${h} * * ${days}`
    }
    if (cronFrequency.value === 'monthly') return `${m} ${h} ${cronMonthDay.value} * *`
    return ''
  }).filter(e => e)
  return exprs.join(';')
}

function parseCronExpression(expr: string) {
  const parts = expr.trim().split(';')
  const times: string[] = []
  let freq = 'daily'
  let weekdays: number[] = [1]
  let monthDay = 1
  for (const p of parts) {
    const f = p.trim().split(/\s+/)
    if (f.length !== 5) continue
    const [m, h, dom, , dow] = f
    times.push(`${h.padStart(2,'0')}:${m.padStart(2,'0')}`)
    if (dom !== '*') { freq = 'monthly'; monthDay = parseInt(dom) }
    else if (dow !== '*') { freq = 'weekly'; weekdays = dow.split(',').map(Number) }
    else { freq = 'daily' }
  }
  cronTimes.value = times.length ? times : ['08:00']
  cronFrequency.value = freq
  cronWeekdays.value = weekdays
  cronMonthDay.value = monthDay
}

const filteredSchedules = computed(() => {
  if (!filterStatus.value) return schedules.value
  return schedules.value.filter(s => s.status === filterStatus.value)
})

function pipelineName(id: string) {
  const p = pipelines.value.find(p => p.id === id)
  return p ? (p.display_name || p.name) : id
}

function formatInterval(seconds?: number) {
  if (!seconds) return '-'
  if (seconds >= 86400) return `每 ${seconds / 86400} 天`
  if (seconds >= 3600) return `每 ${seconds / 3600} 小时`
  if (seconds >= 60) return `每 ${seconds / 60} 分钟`
  return `每 ${seconds} 秒`
}

function cronToHumanReadable(expr?: string): string {
  if (!expr) return '-'
  const parts = expr.trim().split(';').map(p => p.trim()).filter(Boolean)
  const groups: Record<string, string[]> = {}
  const order: string[] = []
  for (const p of parts) {
    const f = p.split(/\s+/)
    if (f.length !== 5) {
      if (!groups['__raw__']) { groups['__raw__'] = []; order.push('__raw__') }
      groups['__raw__'].push(p)
      continue
    }
    const [m, h, dom, , dow] = f
    const time = `${h.padStart(2, '0')}:${m.padStart(2, '0')}`
    let freq: string
    if (dom !== '*') freq = `每月${parseInt(dom)}号`
    else if (dow !== '*') {
      const names = ['一', '二', '三', '四', '五', '六', '日']
      freq = '每' + dow.split(',').map(Number).sort((a, b) => a - b).map((d: number) => '周' + names[d - 1]).join('、')
    } else freq = '每天'
    if (!groups[freq]) { groups[freq] = []; order.push(freq) }
    groups[freq].push(time)
  }
  return order.map(freq => `${freq} ${groups[freq].join('、')}`).join('；')
}

function formatTime(t?: string) {
  if (!t) return '-'
  try {
    let s = t
    // 后端时间为 naive UTC，JSON 无时区后缀，补 'Z' 按_utc 解析再转本地时区显示
    if (!/[zZ]$|[+-]\d{2}:?\d{2}$/.test(s)) s = s + 'Z'
    return new Date(s).toLocaleString('zh-CN')
  } catch { return '-' }
}

function execStatusColor(s: string) {
  return { success: 'success', failed: 'danger', running: 'warning', pending: 'info' }[s] || 'info'
}

function execStatusLabel(s: string) {
  return { success: '成功', failed: '失败', running: '执行中', pending: '等待中', timeout: '超时' }[s] || s
}

function formatResult(r: any): string {
  if (!r) return ''
  if (typeof r === 'string') return r
  // auto_fix 模式：summary 是 Markdown 报告，直接展示保留换行
  if (r.summary) return r.summary
  try { return JSON.stringify(r, null, 2) } catch { return String(r) }
}

async function loadSchedules() {
  loading.value = true
  try {
    schedules.value = await api.get('/schedules', { params: { limit: 100 } }) as any
  } catch { ElMessage.error('加载调度列表失败') }
  finally { loading.value = false }
}

async function loadPipelines() {
  try {
    pipelines.value = await api.get('/pipelines', { params: { limit: 200 } }) as any
  } catch {}
}

function openCreateDialog() {
  editing.value = false
  isBuiltinSchedule.value = false
  form.value = { id: '', name: '', task_target_id: '', schedule_type: 'cron', run_mode: 'normal' }
  cronTimes.value = ['08:00']
  cronFrequency.value = 'daily'
  cronWeekdays.value = [1]
  cronMonthDay.value = 1
  cronTimezone.value = detectedTz
  intervalValue.value = 5
  intervalUnit.value = 60
  showDialog.value = true
}

watch(() => form.value.task_target_id, (newId) => {
  if (editing.value) return
  if (newId) {
    const p = pipelines.value.find(p => p.id === newId)
    if (p) form.value.name = (p.display_name || p.name) + '_调度'
  }
})

watch(() => form.value.run_mode, (mode) => {
  if (editing.value) return
  const suffix = '（自修复）'
  if (mode === 'auto_fix' && !form.value.name.endsWith(suffix)) {
    form.value.name += suffix
  } else if (mode === 'normal' && form.value.name.endsWith(suffix)) {
    form.value.name = form.value.name.slice(0, -suffix.length)
  }
})

function openEditDialog(row: Schedule) {
  editing.value = true
  isBuiltinSchedule.value = !!row.is_builtin
  form.value = {
    id: row.id,
    name: row.name,
    task_target_id: row.task_target_id,
    schedule_type: row.schedule_type === 'manual' ? 'cron' : row.schedule_type,
    run_mode: row.run_mode || 'normal',
  }
  if (row.cron_expression) parseCronExpression(row.cron_expression)
  cronTimezone.value = row.timezone || detectedTz
  if (row.interval_seconds) {
    if (row.interval_seconds >= 86400 && row.interval_seconds % 86400 === 0) { intervalValue.value = row.interval_seconds / 86400; intervalUnit.value = 86400 }
    else if (row.interval_seconds >= 3600 && row.interval_seconds % 3600 === 0) { intervalValue.value = row.interval_seconds / 3600; intervalUnit.value = 3600 }
    else if (row.interval_seconds >= 60 && row.interval_seconds % 60 === 0) { intervalValue.value = row.interval_seconds / 60; intervalUnit.value = 60 }
    else { intervalValue.value = row.interval_seconds; intervalUnit.value = 1 }
  } else { intervalValue.value = 5; intervalUnit.value = 60 }
  showDialog.value = true
}

async function saveSchedule() {
  if (!form.value.name || !form.value.task_target_id) { ElMessage.warning('请填写名称和选择流程'); return }
  saving.value = true
  try {
    const payload: any = {
      name: form.value.name,
      task_type: 'pipeline',
      task_target_id: form.value.task_target_id,
      run_mode: form.value.run_mode,
    }
    if (form.value.schedule_type === 'cron') {
      payload.schedule_type = 'cron'
      payload.cron_expression = buildCronExpression()
      payload.timezone = cronTimezone.value
    } else if (form.value.schedule_type === 'interval') {
      payload.schedule_type = 'interval'
      payload.interval_seconds = intervalValue.value * intervalUnit.value
    } else if (form.value.schedule_type === 'continuous') {
      payload.schedule_type = 'interval'
      payload.interval_seconds = 1
    }
    if (editing.value) {
      await api.put(`/schedules/${form.value.id}`, payload)
    } else {
      await api.post('/schedules', payload)
    }
    ElMessage.success(editing.value ? '已更新' : '已创建')
    showDialog.value = false
    await loadSchedules()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function triggerNow(row: Schedule) {
  try {
    await ElMessageBox.confirm(`立即执行 "${row.name}"？`, '确认', { type: 'info' })
    await api.post(`/schedules/${row.id}/trigger`)
    ElMessage.success('已触发，正在执行…')
    await loadSchedules()
    await viewExecutions(row)
  } catch (e: any) {
    if (e === 'cancel') return
    ElMessage.error(e.response?.data?.detail || '触发失败')
  }
}

async function pauseSchedule(row: Schedule) {
  try { await api.post(`/schedules/${row.id}/pause`); await loadSchedules() }
  catch { ElMessage.error('暂停失败') }
}

async function resumeSchedule(row: Schedule) {
  try { await api.post(`/schedules/${row.id}/resume`); await loadSchedules() }
  catch { ElMessage.error('恢复失败') }
}

async function deleteSchedule(row: Schedule) {
  if (row.is_builtin) { ElMessage.warning('内置调度不可删除'); return }
  try {
    await ElMessageBox.confirm(`删除调度 "${row.name}"？`, '确认删除', { type: 'warning' })
    await api.delete(`/schedules/${row.id}`)
    ElMessage.success('已删除')
    await loadSchedules()
  } catch (e: any) { if (e !== 'cancel') ElMessage.error('删除失败') }
}

async function viewExecutions(row: Schedule) {
  currentScheduleId.value = row.id
  await refreshExecutions()
  showHistory.value = true
  startPolling()
}

async function refreshExecutions() {
  if (!currentScheduleId.value) return
  historyLoading.value = true
  try {
    executions.value = await api.get(`/schedules/${currentScheduleId.value}/executions`, { params: { limit: 20 } }) as any
  } catch { ElMessage.error('加载历史失败') }
  finally { historyLoading.value = false }
}

function startPolling() {
  stopPolling()
  pollTimer.value = window.setInterval(async () => {
    try {
      executions.value = await api.get(`/schedules/${currentScheduleId.value}/executions`, { params: { limit: 20 } }) as any
    } catch {}
  }, 2000)
}

function stopPolling() {
  if (pollTimer.value) {
    clearInterval(pollTimer.value)
    pollTimer.value = null
  }
}

async function viewExecutionDetail(row: any) {
  currentExecutionId.value = row.id
  await refreshExecutionDetail()
  showDetail.value = true
  startDetailPolling()
}

async function refreshExecutionDetail() {
  if (!currentExecutionId.value) return
  detailLoading.value = true
  try {
    executionDetail.value = await api.get(`/schedules/executions/${currentExecutionId.value}`) as any
  } catch { ElMessage.error('加载详情失败') }
  finally { detailLoading.value = false }
}

function startDetailPolling() {
  stopDetailPolling()
  detailPollTimer.value = window.setInterval(async () => {
    await refreshExecutionDetail()
    // 执行完成后停止轮询
    if (executionDetail.value && !['pending', 'running'].includes(executionDetail.value.status)) {
      stopDetailPolling()
    }
  }, 5000)
}

function stopDetailPolling() {
  if (detailPollTimer.value) {
    clearInterval(detailPollTimer.value)
    detailPollTimer.value = null
  }
}

onMounted(() => {
  loadSchedules()
  loadPipelines()
})

onUnmounted(() => {
  stopPolling()
  stopDetailPolling()
})
</script>

<style scoped>
.schedule-page { padding: 20px; }
.toolbar { display: flex; gap: 12px; margin-bottom: 16px; align-items: center; }
.row-desc { font-size: 12px; color: #909399; margin-top: 2px; }
.op-btns {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 4px;
  .el-button { margin-left: 0; padding: 5px 8px; font-size: 12px; }
}
.form-hint { font-size: 12px; color: #909399; margin-top: 4px; display: block; width: 100%; padding-left: 0; }
.cron-times { display: flex; flex-direction: column; gap: 6px; }
.cron-time-row { display: flex; align-items: center; gap: 6px; }
.interval-row { display: flex; gap: 8px; align-items: center; }
.detail-error { margin-top: 12px; }
.detail-logs { margin-top: 12px; }
.detail-result { margin-top: 12px; }
.detail-label { font-weight: 600; font-size: 13px; margin-bottom: 6px; }
.history-header { display: flex; align-items: center; justify-content: space-between; width: 100%; }
.detail-logs pre {
  background: #1e1e1e; color: #d4d4d4; padding: 12px; border-radius: 6px;
  font-size: 12px; max-height: 300px; overflow-y: auto; white-space: pre-wrap; word-break: break-word;
}
.result-pre {
  background: #f5f7fa; padding: 12px; border-radius: 6px;
  font-size: 12px; max-height: 200px; overflow-y: auto; white-space: pre-wrap; word-break: break-word;
  margin: 0;
}
.error-pre {
  background: #fef0f0; color: #f56c6c; padding: 12px; border-radius: 6px;
  font-size: 12px; max-height: 200px; overflow-y: auto; white-space: pre-wrap; word-break: break-word;
  margin: 0;
}
.schedule-dialog-form .el-radio-group {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.schedule-dialog-form .el-radio {
  margin-right: 0;
}
</style>
