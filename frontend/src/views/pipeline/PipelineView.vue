<template>
  <div class="pipeline-page">
    <div class="toolbar">
      <div class="toolbar-left">
        <el-button type="primary" @click="showCreateDialog = true">
          <el-icon><Plus /></el-icon> 新建流程
        </el-button>
        <el-dropdown @command="handleFromSkill">
          <el-button type="success">
            <el-icon><MagicStick /></el-icon> 从Skill生成
            <el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-for="s in skills" :key="s.id" :command="s.id">
                {{ s.display_name || s.name }}
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
      <div class="toolbar-right">
        <el-input
          v-model="searchText"
          placeholder="搜索流程"
          style="width: 220px"
          clearable
          :prefix-icon="Search"
          @input="loadPipelines"
        />
      </div>
    </div>

    <div class="op-grid" v-if="pipelines.length">
      <el-card v-for="pl in pipelines" :key="pl.id" class="operator-card" shadow="hover">
        <template #header>
          <div class="card-header">
            <span class="op-name">{{ pl.display_name || pl.name }}</span>
            <el-tag size="small" type="primary">{{ pl.entry_function || 'main' }}</el-tag>
          </div>
        </template>
        <p class="op-desc">{{ pl.description || '暂无描述' }}</p>
        <div class="op-meta">
          <el-tag v-if="pl.skill_calls?.length" size="small" type="info" effect="plain">
            调用 {{ pl.skill_calls.length }} 个 Skill
          </el-tag>
          <el-tag v-else size="small" type="info" effect="plain">无 Skill 依赖</el-tag>
          <el-tag v-if="pl.source_skill_id" size="small" type="warning" effect="plain">从 Skill 生成</el-tag>
        </div>
        <div class="op-actions">
          <div class="op-actions-row">
            <el-button size="small" type="success" plain @click="openDebug(pl)">
              <el-icon><VideoPlay /></el-icon> 调试
            </el-button>
            <el-button size="small" type="primary" @click="viewCode(pl)">
              <el-icon><Document /></el-icon> 查看代码
            </el-button>
            <el-button size="small" @click="downloadPipeline(pl)">
              <el-icon><Download /></el-icon> 下载
            </el-button>
          </div>
          <div class="op-actions-row">
            <el-button size="small" @click="clonePipeline(pl)">
              <el-icon><CopyDocument /></el-icon> 另存
            </el-button>
            <el-button size="small" type="danger" plain @click="deletePipeline(pl)">
              <el-icon><Delete /></el-icon> 删除
            </el-button>
          </div>
        </div>
      </el-card>
    </div>
    <el-empty v-else description="暂无流程" />

    <!-- 新建流程对话框 -->
    <el-dialog v-model="showCreateDialog" title="新建流程" width="600px">
      <el-form label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="createForm.name" placeholder="英文名称，如 data_cleaning_flow" />
        </el-form-item>
        <el-form-item label="显示名称">
          <el-input v-model="createForm.display_name" placeholder="中文显示名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="createForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="主函数代码">
          <el-input v-model="createForm.main_code" type="textarea" :rows="12" placeholder="def main(...): ..." style="font-family:monospace;font-size:13px" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="doCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 调试对话框（复刻算子调试） -->
    <el-dialog
      v-model="debugDrawer"
      :title="'调试: ' + (debugPipeline?.display_name || debugPipeline?.name || '')"
      width="95%"
      top="2vh"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :before-close="handleDebugBeforeClose"
      @closed="resetDebug"
    >
      <div v-if="debugPipeline" class="debug-layout">
        <div class="debug-left">
          <div class="debug-section-title">
            <span>流程参数</span>
            <el-button size="small" text type="primary" @click="refreshPipelineScript" :loading="saving">
              <el-icon><Refresh /></el-icon> 刷新
            </el-button>
          </div>

          <div class="func-signature">
            <code>{{ debugPipeline?.entry_function || 'main' }}({{ signatureParams }})</code>
            <span class="return-type">→ dict</span>
          </div>

          <div v-if="debugPipeline?.parameters?.length" class="param-group">
            <div class="group-title">参数说明</div>
            <div v-for="(p, i) in debugPipeline.parameters" :key="i" class="param-section">
              <div class="label">
                {{ typeof p === 'string' ? p : p.name }}
                <el-tag v-if="typeof p === 'object' && p.type" size="small" type="primary" effect="plain">{{ p.type }}</el-tag>
                <el-tag v-if="typeof p === 'object' && p.required !== false" size="small" type="danger" effect="plain">必填</el-tag>
                <el-tag v-else-if="typeof p === 'object'" size="small" effect="plain">可选</el-tag>
              </div>
              <div v-if="typeof p === 'object' && p.description" class="param-desc">{{ p.description }}</div>
            </div>
          </div>

          <div class="param-group">
            <div class="group-title">输入参数 (JSON)</div>
            <el-input
              v-model="debugInputs"
              type="textarea"
              :rows="8"
              placeholder='{"datasource_name": "...", "table_name": "..."}'
              style="font-family: 'Consolas', monospace; font-size: 13px"
            />
          </div>

          <el-button type="primary" @click="runDebug" :loading="debugRunning" style="width: 100%; margin-top: 8px">
            <el-icon><CaretRight /></el-icon> 执行调试
          </el-button>
        </div>

        <div class="debug-right">
          <div class="debug-chat-header">
            <el-icon><ChatDotRound /></el-icon>
            <span>AI 调试助手</span>
          </div>
          <div class="debug-message-list" ref="debugMsgListRef" @scroll="onDebugListScroll">
            <div v-if="debugMessages.length === 0 && !debugRunning" class="debug-empty">
              <p>输入消息调试流程代码，例如"帮我修一下这个报错"、"优化这段代码"</p>
            </div>
            <div
              v-for="(msg, idx) in debugMessages"
              :key="idx"
              class="debug-message"
              :class="msg.role"
            >
              <div class="debug-msg-avatar">
                <el-avatar :size="32" v-if="msg.role === 'assistant'" style="background:#409eff">AI</el-avatar>
                <el-avatar :size="32" v-else style="background:#67c23a">我</el-avatar>
              </div>
              <div class="debug-msg-body">
                <div v-if="msg.role === 'user'" class="debug-msg-user">{{ msg.content }}</div>
                <div v-else class="debug-msg-assistant">
                  <div v-if="msg.thinking" class="debug-msg-thinking">
                    <div class="thinking-header" @click="msg.thinkingOpen = !msg.thinkingOpen">
                      <el-icon class="thinking-toggle" :class="{ open: msg.thinkingOpen }"><CaretRight /></el-icon>
                      <span>推理过程<span v-if="msg.model" class="thinking-model">{{ msg.model }}</span></span>
                    </div>
                    <div v-show="msg.thinkingOpen" class="thinking-body">{{ msg.thinking }}</div>
                  </div>
                  <div v-if="msg.content" class="debug-msg-content markdown-body" v-html="renderMarkdown(msg.content)"></div>
                  <div v-if="msg.runResult" class="debug-msg-runresult">
                    <div class="runresult-header">
                      <el-tag :type="msg.runResult.success ? 'success' : 'danger'" size="small">
                        {{ msg.runResult.success ? '执行成功' : '执行失败' }}
                      </el-tag>
                      <span v-if="msg.runResult.execution_time_ms" class="exec-time">{{ msg.runResult.execution_time_ms }}ms</span>
                    </div>
                    <div v-if="msg.runResult.error" class="debug-result-error"><pre>{{ msg.runResult.error }}</pre></div>
                    <div v-if="msg.runResult.stdout" class="debug-result-stdout">
                      <el-collapse>
                        <el-collapse-item title="运行日志">
                          <pre>{{ msg.runResult.stdout }}</pre>
                        </el-collapse-item>
                      </el-collapse>
                    </div>
                    <div v-if="msg.runResult.result != null" class="debug-result-data">
                      <el-collapse>
                        <el-collapse-item title="返回结果">
                          <pre>{{ formatResult(msg.runResult.result) }}</pre>
                        </el-collapse-item>
                      </el-collapse>
                    </div>
                  </div>
                  <div v-if="msg.scriptUpdated" class="debug-msg-script-updated">
                    <el-tag type="warning" size="small">代码已更新: {{ msg.scriptUpdated }}</el-tag>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="(plStreaming || debugRunning) && !debugMessages.length" class="debug-message assistant">
              <div class="debug-msg-avatar"><el-avatar :size="32" style="background:#409eff">AI</el-avatar></div>
              <div class="debug-msg-body">
                <div class="typing-indicator"><span></span><span></span><span></span></div>
              </div>
            </div>
          </div>

          <div class="debug-input-area">
            <el-input
              v-model="debugInput"
              type="textarea"
              :rows="2"
              :autosize="{ minRows: 1, maxRows: 4 }"
              placeholder="输入调试指令... (Enter发送，↑↓切换历史)"
              @keydown="handleDebugKeyDown"
              :disabled="plStreaming"
            />
            <el-button
              v-if="plStreaming"
              type="danger"
              circle
              @click="stopDebugGeneration"
            >
              <el-icon><VideoPause /></el-icon>
            </el-button>
            <el-button
              v-else
              type="primary"
              circle
              :disabled="!debugInput.trim()"
              @click="handleDebugSend"
            >
              <el-icon><Promotion /></el-icon>
            </el-button>
          </div>
        </div>
      </div>
    </el-dialog>

    <!-- 代码查看抽屉 -->
    <el-drawer v-model="showCodeDrawer" :title="codePipeline?.display_name || '流程代码'" size="78%" direction="rtl">
      <template v-if="codePipeline">
        <div class="pl-detail-layout">
          <div class="pl-detail-main">
            <el-tabs v-model="detailTab" class="pl-tabs">
              <el-tab-pane label="Python 代码" name="code">
                <div class="pl-code-header">
                  <span class="pl-code-title">主函数源码</span>
                  <el-button size="small" @click="copyCode">复制代码</el-button>
                </div>
                <div class="pl-code-body">
                  <pre><code class="language-python" v-html="highlightedCode"></code></pre>
                </div>
              </el-tab-pane>
              <el-tab-pane label="流程图" name="flow">
                <div class="pl-flow-header">
                  <span class="pl-code-title">算子调用关系</span>
                  <span class="pl-flow-hint">拖拽画布 · 滚轮缩放</span>
                </div>
                <div class="pl-flow-canvas" ref="flowCanvasRef">
                  <VueFlow
                    v-model="flowElements"
                    :default-viewport="{ x: 0, y: 0, zoom: 1.2 }"
                    :min-zoom="0.3"
                    :max-zoom="3"
                    :nodes-draggable="true"
                    :snap-to-grid="true"
                    :snap-grid="[20, 20]"
                    fit-view-on-init
                    class="pl-vue-flow"
                  >
                    <Background pattern-color="#e8e8e8" :gap="20" />
                    <template #node-custom="nodeProps">
                      <FlowNode :data="nodeProps.data" />
                    </template>
                  </VueFlow>
                </div>
              </el-tab-pane>
            </el-tabs>
          </div>
          <div class="pl-detail-side">
            <el-card header="调用关系" shadow="never" style="margin-bottom:12px">
              <div v-if="codePipeline.skill_calls?.length" class="call-tree">
                <div class="call-root">main()</div>
                <div class="call-connector">├─ ConnectorManager.read_table()</div>
                <div v-for="(call, idx) in codePipeline.skill_calls" :key="idx" class="call-skill">
                  {{ idx === codePipeline.skill_calls.length - 1 ? '└─' : '├─' }}▶ {{ call.skill_name }}
                  <div class="call-func">   └─ {{ call.script }} :: {{ call.function }}()</div>
                </div>
                <div class="call-connector">└─ ConnectorManager.write_table()</div>
              </div>
              <el-empty v-else description="无 Skill 调用" :image-size="40" />
            </el-card>
            <el-card header="执行历史" shadow="never">
              <div v-if="executions.length" class="exec-list">
                <div v-for="e in executions" :key="e.id" class="exec-item" :class="'exec-' + e.status">
                  <span class="exec-status">{{ e.status === 'success' ? '✅' : e.status === 'failed' ? '❌' : '🔄' }}</span>
                  <span class="exec-time">{{ formatTime(e.started_at) }}</span>
                  <span class="exec-duration">{{ e.duration_ms }}ms</span>
                  <span v-if="e.error_message" class="exec-error">{{ e.error_message }}</span>
                </div>
              </div>
              <el-empty v-else description="暂无执行记录" :image-size="40" />
            </el-card>
          </div>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Plus, ArrowDown, MagicStick, Search, VideoPlay, Document, CopyDocument,
  Delete, Download, CaretRight, ChatDotRound, Promotion, VideoPause, Refresh,
} from '@element-plus/icons-vue'
import { VueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import api from '@/api/index'
import hljs from 'highlight.js/lib/core'
import python from 'highlight.js/lib/languages/python'
import 'highlight.js/styles/vs2015.css'
import markdownIt from 'markdown-it'
import FlowNode from './FlowNode.vue'

hljs.registerLanguage('python', python)

const md = markdownIt({ html: false, breaks: true, linkify: true })
function renderMarkdown(text: string): string {
  return md.render(text || '')
}

interface Pipeline {
  id: string
  name: string
  display_name?: string
  description?: string
  main_code?: string
  entry_function: string
  parameters?: any[]
  skill_calls?: any[]
  source_skill_id?: string
  version: number
  tags?: string[]
  category?: string
  visibility?: string
  is_active: boolean
  created_at: string
  updated_at?: string
}

interface Execution {
  id: string
  pipeline_id: string
  status: string
  inputs?: any
  outputs?: any
  started_at?: string
  finished_at?: string
  duration_ms?: number
  error_message?: string
  logs?: string
  created_at: string
}

interface DebugMessage {
  role: 'user' | 'assistant'
  content: string
  thinking?: string
  thinkingOpen?: boolean
  runResult?: any
  scriptUpdated?: string
  model?: string
}

const pipelines = ref<Pipeline[]>([])
const skills = ref<any[]>([])
const searchText = ref('')
const showCreateDialog = ref(false)
const showCodeDrawer = ref(false)
const codePipeline = ref<Pipeline | null>(null)
const executions = ref<Execution[]>([])
const detailTab = ref('code')
const flowCanvasRef = ref<HTMLElement | null>(null)
const saving = ref(false)

const createForm = ref({
  name: '',
  display_name: '',
  description: '',
  main_code: '',
})

const highlightedCode = computed(() => {
  if (!codePipeline.value?.main_code) return ''
  return hljs.highlight(codePipeline.value.main_code, { language: 'python' }).value
})

const flowElements = ref<any[]>([])

function buildFlowGraph(pipeline: Pipeline) {
  const nodes: any[] = []
  const edges: any[] = []
  const skillCalls = pipeline.skill_calls || []
  const hasCode = !!pipeline.main_code?.includes('read_table') || !!pipeline.main_code?.includes('write_table')

  const startY = 60
  const spacing = 100
  let y = startY

  nodes.push({
    id: 'main',
    type: 'custom',
    position: { x: 250, y },
    data: { label: 'main()', sub: '入口函数', color: '#409eff' },
    draggable: true,
  })
  y += spacing

  if (hasCode || skillCalls.length > 0) {
    nodes.push({
      id: 'read',
      type: 'custom',
      position: { x: 250, y },
      data: { label: 'read_table()', sub: 'ConnectorManager', color: '#909399' },
      draggable: true,
    })
    edges.push({ id: 'e-main-read', source: 'main', target: 'read', type: 'smoothstep', animated: true, style: { stroke: '#b0b0b0', strokeWidth: 2 } })
    y += spacing
  }

  let prevId = 'read'
  skillCalls.forEach((call: any, i: number) => {
    const id = `skill-${i}`
    nodes.push({
      id,
      type: 'custom',
      position: { x: 250, y },
      data: { label: call.function + '()', sub: `${call.skill_name} › ${call.script}`, color: '#67c23a' },
      draggable: true,
    })
    edges.push({ id: `e-${prevId}-${id}`, source: prevId, target: id, type: 'smoothstep', animated: true, style: { stroke: '#67c23a', strokeWidth: 2 } })
    prevId = id
    y += spacing
  })

  if (hasCode || skillCalls.length > 0) {
    nodes.push({
      id: 'write',
      type: 'custom',
      position: { x: 250, y },
      data: { label: 'write_table()', sub: 'ConnectorManager', color: '#909399' },
      draggable: true,
    })
    edges.push({ id: `e-${prevId}-write`, source: prevId, target: 'write', type: 'smoothstep', animated: true, style: { stroke: '#b0b0b0', strokeWidth: 2 } })
  }

  flowElements.value = [...nodes, ...edges]
}

watch(codePipeline, (pl) => {
  if (pl) buildFlowGraph(pl)
})

async function loadPipelines() {
  try {
    const params: any = {}
    if (searchText.value) params.search = searchText.value
    pipelines.value = await api.get('/pipelines', { params }) as any
  } catch {
    ElMessage.error('加载流程列表失败')
  }
}

async function loadSkills() {
  try {
    skills.value = await api.get('/skills', { params: { limit: 100 } }) as any
  } catch {}
}

async function doCreate() {
  if (!createForm.value.name) { ElMessage.warning('请输入名称'); return }
  try {
    await api.post('/pipelines', createForm.value)
    ElMessage.success('流程已创建')
    showCreateDialog.value = false
    createForm.value = { name: '', display_name: '', description: '', main_code: '' }
    await loadPipelines()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '创建失败')
  }
}

async function handleFromSkill(skillId: string) {
  const skill = skills.value.find(s => s.id === skillId)
  if (!skill) return
  try {
    await ElMessageBox.confirm(`从 Skill "${skill.display_name || skill.name}" 生成流程？`, '生成流程', { type: 'info' })
    const data = await api.post(`/pipelines/from-skill/${skillId}`)
    ElMessage.success(`流程 "${(data as any).display_name || (data as any).name}" 已生成`)
    await loadPipelines()
  } catch (e: any) {
    if (e === 'cancel') return
    ElMessage.error(e.response?.data?.detail || '生成失败')
  }
}

async function viewCode(pl: Pipeline) {
  try {
    codePipeline.value = await api.get(`/pipelines/${pl.id}`) as any
    detailTab.value = 'code'
    showCodeDrawer.value = true
    await loadExecutions(pl.id)
  } catch {
    ElMessage.error('加载流程失败')
  }
}

async function loadExecutions(pipelineId: string) {
  try {
    executions.value = await api.get(`/pipelines/${pipelineId}/executions`, { params: { limit: 20 } }) as any
  } catch {}
}

function copyCode() {
  if (codePipeline.value?.main_code) {
    navigator.clipboard.writeText(codePipeline.value.main_code)
    ElMessage.success('代码已复制')
  }
}

async function clonePipeline(pl: Pipeline) {
  try {
    await api.post(`/pipelines/${pl.id}/clone`)
    ElMessage.success('已复制')
    await loadPipelines()
  } catch {
    ElMessage.error('复制失败')
  }
}

function downloadPipeline(pl: Pipeline) {
  const code = pl.main_code || ''
  if (!code) { ElMessage.warning('该流程没有可下载的代码'); return }
  const blob = new Blob([code], { type: 'text/x-python;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${pl.name || 'pipeline'}.py`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
  ElMessage.success('代码已下载')
}

async function deletePipeline(pl: Pipeline) {
  try {
    await ElMessageBox.confirm(`确定删除 "${pl.display_name || pl.name}"？`, '确认删除', { type: 'warning' })
    await api.delete(`/pipelines/${pl.id}`)
    ElMessage.success('已删除')
    await loadPipelines()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
}

function formatTime(t?: string) {
  if (!t) return ''
  return new Date(t).toLocaleString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

// ==================== 调试弹窗（复刻算子调试） ====================
const debugDrawer = ref(false)
const debugPipeline = ref<Pipeline | null>(null)

// 息屏防护：页面不可见时阻止对话框关闭
watch(debugDrawer, (newVal, oldVal) => {
  if (oldVal === true && newVal === false && document.hidden) {
    nextTick(() => { debugDrawer.value = true })
  }
})
const debugMessages = ref<DebugMessage[]>([])
const debugInput = ref('')
const debugInputs = ref('{}')
const debugRunning = ref(false)
const plStreaming = ref(false)
const debugMsgListRef = ref<HTMLElement>()
let debugAbortController: AbortController | null = null

const signatureParams = computed(() => {
  const params = debugPipeline.value?.parameters as any[] | undefined
  if (!params || !params.length) return 'inputs'
  return params.map(p => {
    const name = typeof p === 'string' ? p : p.name
    const required = typeof p === 'object' ? p.required !== false : true
    return required ? name : `${name}=...`
  }).join(', ')
})
const debugPinnedToBottom = ref(true)

// 输入历史
const HISTORY_KEY = 'dc_pipeline_debug_history'
const HISTORY_MAX = 100
const debugHistory = ref<string[]>(loadDebugHistory())
const debugHistoryIdx = ref(-1)
const debugDraft = ref('')

function loadDebugHistory(): string[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}
function saveDebugHistory(list: string[]) {
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(-HISTORY_MAX))) } catch {}
}

function scrollDebugToBottom(force = false) {
  const el = debugMsgListRef.value
  if (!el) return
  if (!force && !debugPinnedToBottom.value) return
  el.scrollTop = el.scrollHeight
}
function scrollThinkingBodyToBottom(msgIdx: number) {
  nextTick(() => {
    const list = debugMsgListRef.value
    if (!list) return
    const msgs = list.querySelectorAll('.debug-message')
    const target = msgs[msgIdx] as HTMLElement | undefined
    if (!target) return
    const body = target.querySelector('.thinking-body') as HTMLElement | null
    if (body) body.scrollTop = body.scrollHeight
  })
}
function onDebugListScroll() {
  const el = debugMsgListRef.value
  if (!el) return
  debugPinnedToBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

function openDebug(pl: Pipeline) {
  debugPipeline.value = { ...pl }
  debugMessages.value = []
  debugInput.value = ''
  const params = (pl as any).parameters as any[] | undefined
  if (params && params.length) {
    const example: Record<string, any> = {}
    for (const p of params) {
      const name = typeof p === 'string' ? p : p.name
      if (!name || name.startsWith('*')) continue
      const required = typeof p === 'object' ? p.required !== false : true
      if (required) {
        example[name] = typeof p === 'object' && p.description ? p.description : ''
      }
    }
    debugInputs.value = JSON.stringify(example, null, 2)
  } else {
    debugInputs.value = '{}'
  }
  debugDrawer.value = true
  debugPinnedToBottom.value = true
}

function resetDebug() {
  if (debugAbortController) {
    debugAbortController.abort()
    debugAbortController = null
  }
  plStreaming.value = false
}

function handleDebugBeforeClose(done: () => void) {
  if (plStreaming.value || debugRunning.value) {
    ElMessage.warning('正在执行中，请先等待完成或点击停止')
    return
  }
  done()
}

async function refreshPipelineScript() {
  if (!debugPipeline.value) return
  saving.value = true
  try {
    const fresh = await api.get(`/pipelines/${debugPipeline.value.id}`)
    debugPipeline.value = fresh as any
    ElMessage.success('流程数据已刷新')
    await loadPipelines()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '刷新失败')
  } finally {
    saving.value = false
  }
}

async function runDebug() {
  if (!debugPipeline.value) return
  let inputs: any = {}
  try {
    inputs = JSON.parse(debugInputs.value || '{}')
  } catch {
    ElMessage.warning('输入参数 JSON 格式错误')
    return
  }
  debugRunning.value = true
  try {
    const res = await api.post(`/pipelines/${debugPipeline.value.id}/run`, { inputs }) as any
    const success = res?.status === 'success'
    debugMessages.value.push({
      role: 'assistant',
      content: success ? '执行完成' : '执行失败',
      runResult: {
        success,
        result: res?.outputs ?? null,
        error: res?.error_message || null,
        stdout: res?.logs || null,
        execution_time_ms: res?.duration_ms ?? null,
      },
    })
    if (codePipeline.value?.id === debugPipeline.value.id) {
      await loadExecutions(debugPipeline.value.id)
    }
  } catch (e: any) {
    debugMessages.value.push({
      role: 'assistant',
      content: '执行失败',
      runResult: { success: false, error: e.response?.data?.detail || String(e) },
    })
  } finally {
    debugRunning.value = false
    nextTick(() => scrollDebugToBottom(true))
  }
}

function formatResult(result: any): string {
  try { return JSON.stringify(result, null, 2) } catch { return String(result) }
}

function stopDebugGeneration() {
  if (debugAbortController) {
    debugAbortController.abort()
  }
}

function handleDebugKeyDown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleDebugSend()
    return
  }
  // ↑↓ 切换历史
  if (e.key === 'ArrowUp') {
    if (debugHistory.value.length === 0) return
    e.preventDefault()
    if (debugHistoryIdx.value === -1) {
      debugDraft.value = debugInput.value
      debugHistoryIdx.value = debugHistory.value.length - 1
    } else if (debugHistoryIdx.value > 0) {
      debugHistoryIdx.value--
    }
    debugInput.value = debugHistory.value[debugHistoryIdx.value]
  } else if (e.key === 'ArrowDown') {
    if (debugHistoryIdx.value === -1) return
    e.preventDefault()
    if (debugHistoryIdx.value < debugHistory.value.length - 1) {
      debugHistoryIdx.value++
      debugInput.value = debugHistory.value[debugHistoryIdx.value]
    } else {
      debugHistoryIdx.value = -1
      debugInput.value = debugDraft.value
    }
  }
}

async function handleDebugSend() {
  if (!debugPipeline.value || !debugInput.value.trim() || plStreaming.value) return

  const userMsg = debugInput.value.trim()
  if (debugHistory.value[debugHistory.value.length - 1] !== userMsg) {
    debugHistory.value.push(userMsg)
    if (debugHistory.value.length > HISTORY_MAX) debugHistory.value = debugHistory.value.slice(-HISTORY_MAX)
    saveDebugHistory(debugHistory.value)
  }
  debugHistoryIdx.value = -1

  debugMessages.value.push({ role: 'user', content: userMsg })
  debugInput.value = ''
  plStreaming.value = true
  debugAbortController = new AbortController()

  const assistantIdx = debugMessages.value.length
  debugMessages.value.push({ role: 'assistant', content: '', thinking: '', thinkingOpen: false })
  debugPinnedToBottom.value = true
  await nextTick()
  scrollDebugToBottom(true)

  let scriptChanged = false
  let streamOk = false

  try {
    const token = localStorage.getItem('access_token')
    const history = debugMessages.value.slice(0, assistantIdx).map(m => ({
      role: m.role,
      content: m.content + (m.runResult ? `\n\n[执行结果: ${m.runResult.success ? '成功' : '失败'}]` + (m.runResult.error ? ` 错误: ${m.runResult.error}` : '') : '') + (m.scriptUpdated ? `\n\n[代码已更新: ${m.scriptUpdated}]` : ''),
    }))

    const contextData: Record<string, string> = {}
    if (debugInputs.value.trim()) contextData['inputs'] = debugInputs.value.trim()
    const lastRunMsg = [...debugMessages.value].reverse().find(m => m.runResult)
    if (lastRunMsg?.runResult) {
      contextData['last_result'] = lastRunMsg.runResult.success ? '成功' : '失败'
      if (lastRunMsg.runResult.error) contextData['last_error'] = lastRunMsg.runResult.error
    }

    const response = await fetch(`/api/v1/pipelines/${debugPipeline.value.id}/debug-chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ message: userMsg, history, context: contextData }),
      signal: debugAbortController.signal,
    })

    if (!response.ok) {
      const errText = await response.text()
      throw new Error(errText || `HTTP ${response.status}`)
    }

    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let thinkingDone = false

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed.startsWith('data: ')) continue

        try {
          const data = JSON.parse(trimmed.slice(6))
          const msg = debugMessages.value[assistantIdx]

          if (data.type === 'model') {
            msg.model = data.content
          } else if (data.type === 'clear_thinking') {
            msg.thinking = ''
            msg.content = ''
            msg.thinkingOpen = true
            thinkingDone = false
          } else if (data.type === 'thinking') {
            if (thinkingDone && msg.thinking) {
              msg.thinking += '\n\n--- 新一轮推理 ---\n'
              msg.thinkingOpen = true
              thinkingDone = false
            }
            if (!msg.thinking) msg.thinkingOpen = true
            msg.thinking = (msg.thinking || '') + data.content
            scrollThinkingBodyToBottom(assistantIdx)
          } else if (data.type === 'content') {
            if (!thinkingDone && msg.thinking) { thinkingDone = true; msg.thinkingOpen = false; }
            msg.content += data.content
          } else if (data.type === 'script_updated') {
            msg.scriptUpdated = data.script_name
            scriptChanged = true
            try {
              const fresh = await api.get(`/pipelines/${debugPipeline.value!.id}`)
              debugPipeline.value = fresh as any
            } catch { /* skip */ }
          } else if (data.type === 'error') {
            msg.content += `\n\n错误: ${data.content || '未知错误'}`
          } else if (data.type === 'inspecting') {
            msg.content += `\n\n🔍 ${data.message || 'DataInspector 正在检查数据质量...'}\n`
            msg.thinkingOpen = true
            thinkingDone = true
          } else if (data.type === 'retry') {
            msg.content += `\n\n---\n🔄 ${data.message || '第' + data.round + '次修复尝试'}\n`
            msg.thinkingOpen = true
            thinkingDone = true
          } else if (data.type === 'round') {
            msg.content += `\n\n═══ 第${data.round}轮修改 ═══\n`
            msg.thinkingOpen = true
            thinkingDone = true
          } else if (data.type === 'give_up') {
            msg.content += `\n\n⚠ **多次修复失败，无法自动修复**\n\n${data.reason || ''}`
          } else if (data.type === 'fatal') {
            const issues = data.issues || []
            let fatalText = `\n\n🚫 **致命问题——数据违反法律法规，已停止处理**\n\n${data.summary || ''}\n`
            for (const issue of issues) {
              fatalText += `\n- [FATAL] ${issue.description || ''}`
              if (issue.suggestion) fatalText += `\n  → ${issue.suggestion}`
            }
            msg.content += fatalText
          } else if (data.type === 'warning_confirmation') {
            const issues = data.issues || []
            let warnText = `\n\n⚠ **检查发现以下警告问题，是否需要修复？**\n\n${data.summary || ''}\n`
            for (const issue of issues) {
              warnText += `\n- [WARNING] ${issue.description || ''}`
              if (issue.column) warnText += ` (列: ${issue.column})`
              if (issue.suggestion) warnText += `\n  → ${issue.suggestion}`
            }
            warnText += '\n\n> 如需修复，请回复"修复警告问题"'
            msg.content += warnText
          }
        } catch { /* skip */ }
      }
      nextTick(() => scrollDebugToBottom())
    }

    const finalMsg = debugMessages.value[assistantIdx]
    if (finalMsg.thinking && !thinkingDone) {
      finalMsg.thinking = ''
    }
    streamOk = true
  } catch (e: any) {
    if (e.name === 'AbortError') {
      const msg = debugMessages.value[assistantIdx]
      if (msg.content) msg.content += '\n\n*[已停止生成]*'
      else msg.content = '*[已停止生成]*'
    } else {
      debugMessages.value[assistantIdx].content = `请求出错: ${e.message || String(e)}`
    }
  } finally {
    plStreaming.value = false
    debugAbortController = null
    await nextTick()
    scrollDebugToBottom()
  }

  // 代码被 AI 更新后，若左侧有输入参数，自动重跑一次流程查看结果
  if (scriptChanged && streamOk && debugPipeline.value) {
    const assistantMsg = debugMessages.value[assistantIdx]
    try {
      JSON.parse(debugInputs.value || '{}')
      if (assistantMsg) assistantMsg.content += '\n\n> 代码已更新，正在重新执行流程…'
      await runDebug()
    } catch {
      if (assistantMsg) assistantMsg.content += '\n\n> 代码已更新。左侧填写有效 JSON 参数后点击「执行调试」查看结果。'
    }
  }
}

onMounted(() => {
  loadPipelines()
  loadSkills()
})
</script>

<style lang="scss" scoped>
.pipeline-page {
  padding: 20px;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  gap: 12px;

  .toolbar-left { display: flex; gap: 12px; align-items: center; }
  .toolbar-right { display: flex; gap: 12px; align-items: center; }
}

.op-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
  align-items: stretch;
}

.operator-card {
  height: 100%;
  display: flex;
  flex-direction: column;

  :deep(.el-card__header) { flex-shrink: 0; }
  :deep(.el-card__body) { flex: 1; display: flex; flex-direction: column; }

  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
    .op-name {
      font-weight: 600;
      font-size: 15px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }
  .op-desc {
    color: #666;
    font-size: 13px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    margin: 0;
  }
  .op-meta {
    margin: 8px 0;
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    min-height: 26px;
  }
  .op-actions {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-top: auto;
    padding-top: 12px;

    .op-actions-row {
      display: flex;
      gap: 4px;
      align-items: center;
    }
  }
}

.debug-layout {
  display: flex;
  gap: 16px;
  height: 75vh;
}

.debug-left {
  width: 380px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  gap: 8px;
}

.debug-section-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 4px;
  color: #303133;
}

.debug-right {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  overflow: hidden;
  background: #f9fafb;
}

.func-signature {
  background: #f0f5ff;
  border: 1px solid #d6e4ff;
  border-radius: 6px;
  padding: 10px 14px;
  margin-bottom: 4px;
  code { font-family: 'Consolas', 'Monaco', 'Courier New', monospace; font-size: 13px; color: #1d39c4; }
  .return-type { font-size: 12px; color: #52c41a; margin-left: 8px; }
}

.param-group {
  margin-bottom: 4px;
  .group-title {
    font-size: 13px;
    font-weight: 600;
    color: #303133;
    margin-bottom: 8px;
    padding-left: 4px;
    border-left: 3px solid #409eff;
  }
}

.param-section {
  margin-bottom: 6px;
  .label {
    font-size: 13px;
    color: #606266;
    margin-bottom: 2px;
    display: flex;
    align-items: center;
    gap: 4px;
    flex-wrap: wrap;
  }
  .param-desc {
    font-size: 12px;
    color: #909399;
    padding-left: 2px;
  }
}

.debug-msg-runresult {
  margin-top: 6px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  overflow: hidden;

  .runresult-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 10px;
    background: #f5f7fa;
    border-bottom: 1px solid #e4e7ed;
  }
  .exec-time { font-size: 11px; color: #909399; }
  .debug-result-error {
    padding: 6px 10px;
    pre { margin: 0; font-size: 12px; color: #f56c6c; white-space: pre-wrap; word-break: break-all; }
  }
  .debug-result-stdout,
  .debug-result-data {
    :deep(.el-collapse-item__header) { font-size: 12px; height: 28px; line-height: 28px; padding-left: 10px; }
    pre { margin: 0; font-size: 11px; white-space: pre-wrap; word-break: break-all; max-height: 160px; overflow-y: auto; }
  }
}

.debug-chat-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  border-bottom: 1px solid #ebeef5;
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  background: #fff;
}

.debug-message-list {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.debug-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 8px;
  color: #c0c4cc;
  p { font-size: 14px; text-align: center; line-height: 1.6; padding: 0 12px; }
}

.debug-message {
  display: flex;
  gap: 8px;
  max-width: 100%;
  min-width: 0;

  &.user {
    align-self: flex-end;
    flex-direction: row-reverse;
    .debug-msg-user {
      background: #409eff;
      color: #fff;
      border-radius: 10px 10px 2px 10px;
      padding: 6px 12px;
      font-size: 13px;
      line-height: 1.5;
      word-break: break-word;
      overflow-wrap: break-word;
      max-width: 85%;
      width: fit-content;
    }
  }

  &.assistant {
    align-self: flex-start;
    max-width: 100%;
    .debug-msg-assistant {
      background: #fff;
      border: 1px solid #e4e7ed;
      border-radius: 10px 10px 10px 2px;
      padding: 8px 12px;
      max-width: 100%;
      min-width: 0;
      overflow-wrap: break-word;
      word-break: break-word;
    }
  }
}

.debug-msg-avatar { flex-shrink: 0; }
.debug-msg-body { flex: 1; min-width: 0; max-width: 100%; overflow: hidden; }
.debug-message.user .debug-msg-body { display: flex; flex-direction: column; align-items: flex-end; }

.debug-msg-thinking {
  margin-bottom: 8px;
  border: 1px solid #d9ecff;
  border-radius: 6px;
  overflow: hidden;
  background: #ecf5ff;

  .thinking-header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 12px;
    font-size: 13px;
    color: #409eff;
    font-weight: 500;
    border-bottom: 1px solid #d9ecff;
    cursor: pointer;
    user-select: none;
    .thinking-toggle { transition: transform 0.2s; }
    .thinking-toggle.open { transform: rotate(90deg); }
    .thinking-model { margin-left: 8px; font-size: 11px; color: #909399; font-weight: normal; }
  }

  .thinking-body {
    padding: 10px 12px;
    font-size: 13px;
    color: #606266;
    line-height: 1.6;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 300px;
    overflow-y: auto;
  }
}

.debug-msg-content {
  font-size: 13px;
  line-height: 1.6;
  overflow-wrap: break-word;
  word-break: break-word;
  :deep(pre) { white-space: pre-wrap; word-break: break-all; overflow-x: auto; max-width: 100%; }
  :deep(table) { width: 100%; table-layout: fixed; word-break: break-all; }
  :deep(code) { white-space: pre-wrap; word-break: break-all; }
}

.debug-msg-script-updated { margin-top: 6px; }

.debug-input-area {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  padding: 12px 16px;
  border-top: 1px solid #ebeef5;
  background: #fff;
  .el-textarea { flex: 1; font-size: 14px; }
  .el-button { margin-bottom: 4px; }
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 6px 0;
  span {
    width: 6px; height: 6px; border-radius: 50%; background: #c0c4cc;
    animation: typing 1.4s infinite ease-in-out both;
    &:nth-child(1) { animation-delay: 0s; }
    &:nth-child(2) { animation-delay: 0.2s; }
    &:nth-child(3) { animation-delay: 0.4s; }
  }
}

@keyframes typing {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

/* 代码查看抽屉 */
.pl-detail-layout { display: flex; gap: 16px; height: calc(100vh - 120px); }
.pl-detail-main { flex: 1; overflow: hidden; display: flex; flex-direction: column; min-width: 0; }
.pl-tabs { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.pl-tabs :deep(.el-tabs__content) { flex: 1; overflow: hidden; }
.pl-tabs :deep(.el-tab-pane) { height: 100%; display: flex; flex-direction: column; overflow: hidden; }
.pl-code-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.pl-code-title { font-weight: 600; font-size: 14px; }
.pl-code-body {
  flex: 1; overflow: auto; background: #ffffff; color: #303133;
  border: 1px solid #ebeef5; border-radius: 8px; padding: 16px;
  pre { margin: 0; font-size: 13px; line-height: 1.6; white-space: pre-wrap; word-break: break-all; }
  code { font-family: 'Cascadia Code', 'Consolas', monospace; }
}
.pl-flow-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.pl-flow-hint { font-size: 12px; color: #909399; }
.pl-flow-canvas {
  flex: 1; min-height: 400px; border: 1px solid #ebeef5; border-radius: 8px; overflow: hidden; background: #fafbfc;
}
.pl-vue-flow { width: 100%; height: 100%; }
.pl-detail-side { width: 260px; flex-shrink: 0; overflow-y: auto; }
.call-tree { font-size: 13px; font-family: monospace; line-height: 1.7; padding-top: 4px; }
.call-root { color: #409eff; font-weight: 600; }
.call-connector { color: #909399; padding-left: 4px; }
.call-skill { color: #67c23a; padding-left: 4px; }
.call-func { color: #909399; padding-left: 16px; font-size: 12px; }
.exec-list { font-size: 12px; }
.exec-item { padding: 6px 0; border-bottom: 1px solid #ebeef5; }
.exec-item:last-child { border-bottom: none; }
.exec-status { margin-right: 6px; }
.exec-time { color: #909399; margin-right: 8px; }
.exec-duration { color: #606266; }
.exec-error { color: #f56c6c; display: block; margin-top: 2px; }
</style>

<style lang="scss">
.debug-layout {
  .el-textarea__inner,
  .el-input__inner {
    &::placeholder { white-space: pre-wrap; word-break: break-all; }
  }
}

.markdown-body {
  font-size: 14px;
  line-height: 1.8;
  color: #303133;

  h1, h2, h3, h4 { margin-top: 16px; margin-bottom: 8px; font-weight: 600; color: #1d1d1f; }
  h1 { font-size: 22px; border-bottom: 2px solid #409eff; padding-bottom: 6px; }
  h2 { font-size: 19px; border-bottom: 1px solid #e4e7ed; padding-bottom: 4px; }
  h3 { font-size: 16px; }
  p { margin: 8px 0; }
  ul, ol { padding-left: 24px; margin: 8px 0; }
  li { margin: 4px 0; }
  code {
    background: #f0f2f5; padding: 2px 6px; border-radius: 4px;
    font-family: 'Consolas', monospace; font-size: 13px; color: #d63384;
  }
  pre {
    background: #ffffff; border: 1px solid #ebeef5; border-radius: 8px; padding: 14px 18px; overflow-x: auto;
    code { background: none; color: #303133; padding: 0; }
  }
  blockquote {
    border-left: 4px solid #409eff; padding: 8px 16px; margin: 12px 0;
    background: #f0f5ff; color: #606266; border-radius: 0 6px 6px 0;
  }
  table { width: 100%; border-collapse: collapse; margin: 12px 0;
    th, td { border: 1px solid #dcdfe6; padding: 8px 12px; text-align: left; }
    th { background: #f5f7fa; font-weight: 600; }
  }
  a { color: #409eff; }
  hr { border: none; border-top: 1px solid #e4e7ed; margin: 20px 0; }
  strong { font-weight: 600; color: #1d1d1f; }
}
</style>
