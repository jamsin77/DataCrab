<template>
  <div class="pipeline-view">
    <div class="pl-toolbar">
      <el-button type="primary" @click="showCreateDialog = true">新建流程</el-button>
      <el-dropdown @command="handleFromSkill" style="margin-left:8px">
        <el-button>从Skill生成 <el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item v-for="s in skills" :key="s.id" :command="s.id">
              {{ s.display_name || s.name }}
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <el-input v-model="searchText" placeholder="搜索流程..." size="small" style="width:200px;margin-left:12px" clearable @input="loadPipelines" />
    </div>

    <div class="pl-grid" v-if="pipelines.length">
      <el-card v-for="pl in pipelines" :key="pl.id" class="pl-card" shadow="hover">
        <div class="pl-card-header">
          <span class="pl-card-name">{{ pl.display_name || pl.name }}</span>
          <el-tag size="small" type="primary">主函数</el-tag>
        </div>
        <div class="pl-card-desc">{{ pl.description || '暂无描述' }}</div>
        <div class="pl-card-meta">
          <span v-if="pl.skill_calls?.length">调用 {{ pl.skill_calls.length }} 个 Skill 脚本</span>
          <span v-else>无 Skill 依赖</span>
          <span v-if="pl.source_skill_id" style="margin-left:8px;color:#909399">· 从 Skill 生成</span>
        </div>
        <div class="pl-card-actions">
          <el-button size="small" type="primary" text @click="viewCode(pl)">查看代码</el-button>
          <el-button size="small" type="success" text @click="runPipeline(pl)">运行</el-button>
          <el-button size="small" text @click="clonePipeline(pl)">复制</el-button>
          <el-button size="small" type="danger" text @click="deletePipeline(pl)">删除</el-button>
        </div>
      </el-card>
    </div>
    <el-empty v-else description="暂无流程" />

    <!-- 创建流程对话框 -->
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

    <!-- 运行对话框 -->
    <el-dialog v-model="showRunDialog" title="运行流程" width="500px">
      <el-form label-width="80px">
        <el-form-item label="参数(JSON)">
          <el-input v-model="runInputs" type="textarea" :rows="6" placeholder='{"datasource_name": "...", "table_name": "..."}' style="font-family:monospace" />
        </el-form-item>
      </el-form>
      <div v-if="runResult" class="run-result" :class="runResult.status">
        <div class="run-status">{{ runResult.status === 'success' ? '✅ 成功' : '❌ 失败' }} {{ runResult.duration_ms }}ms</div>
        <pre v-if="runResult.outputs" class="run-output">{{ JSON.stringify(runResult.outputs, null, 2) }}</pre>
        <pre v-if="runResult.error_message" class="run-error">{{ runResult.error_message }}</pre>
      </div>
      <template #footer>
        <el-button @click="showRunDialog = false">关闭</el-button>
        <el-button type="primary" :loading="running" @click="doRun">{{ running ? '执行中...' : '执行' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
import { VueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import api from '@/api/index'
import hljs from 'highlight.js/lib/core'
import python from 'highlight.js/lib/languages/python'
import 'highlight.js/styles/vs2015.css'
import FlowNode from './FlowNode.vue'

hljs.registerLanguage('python', python)

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

const pipelines = ref<Pipeline[]>([])
const skills = ref<any[]>([])
const searchText = ref('')
const showCreateDialog = ref(false)
const showCodeDrawer = ref(false)
const showRunDialog = ref(false)
const running = ref(false)
const runInputs = ref('{}')
const runResult = ref<any>(null)
const runTarget = ref<Pipeline | null>(null)
const codePipeline = ref<Pipeline | null>(null)
const executions = ref<Execution[]>([])
const detailTab = ref('code')
const flowCanvasRef = ref<HTMLElement | null>(null)

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
    edges.push({
      id: 'e-main-read',
      source: 'main',
      target: 'read',
      type: 'smoothstep',
      animated: true,
      style: { stroke: '#b0b0b0', strokeWidth: 2 },
    })
    y += spacing
  }

  let prevId = 'read'
  skillCalls.forEach((call: any, i: number) => {
    const id = `skill-${i}`
    nodes.push({
      id,
      type: 'custom',
      position: { x: 250, y },
      data: {
        label: call.function + '()',
        sub: `${call.skill_name} › ${call.script}`,
        color: '#67c23a',
      },
      draggable: true,
    })
    edges.push({
      id: `e-${prevId}-${id}`,
      source: prevId,
      target: id,
      type: 'smoothstep',
      animated: true,
      style: { stroke: '#67c23a', strokeWidth: 2 },
    })
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
    edges.push({
      id: `e-${prevId}-write`,
      source: prevId,
      target: 'write',
      type: 'smoothstep',
      animated: true,
      style: { stroke: '#b0b0b0', strokeWidth: 2 },
    })
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
  } catch (e: any) {
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

function runPipeline(pl: Pipeline) {
  runTarget.value = pl
  runInputs.value = '{\n  "datasource_name": "",\n  "table_name": ""\n}'
  runResult.value = null
  showRunDialog.value = true
}

async function doRun() {
  if (!runTarget.value) return
  running.value = true
  try {
    let inputs: any = {}
    try { inputs = JSON.parse(runInputs.value) } catch { ElMessage.warning('参数 JSON 格式错误'); running.value = false; return }
    const result = await api.post(`/pipelines/${runTarget.value.id}/run`, { inputs }) as any
    runResult.value = result
  } catch (e: any) {
    runResult.value = { status: 'failed', error_message: e.response?.data?.detail || '执行失败' }
  } finally {
    running.value = false
    if (codePipeline.value) await loadExecutions(codePipeline.value.id)
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

onMounted(() => {
  loadPipelines()
  loadSkills()
})
</script>

<style scoped>
.pipeline-view { padding: 20px; }
.pl-toolbar { margin-bottom: 20px; display: flex; align-items: center; }
.pl-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}
.pl-card { cursor: default; }
.pl-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.pl-card-name { font-weight: 600; font-size: 15px; color: #303133; }
.pl-card-desc { font-size: 13px; color: #909399; margin-bottom: 10px; min-height: 20px; }
.pl-card-meta { font-size: 12px; color: #909399; margin-bottom: 10px; }
.pl-card-actions { display: flex; gap: 4px; }

.pl-detail-layout {
  display: flex;
  gap: 16px;
  height: calc(100vh - 120px);
}
.pl-detail-main {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.pl-tabs {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.pl-tabs :deep(.el-tabs__content) {
  flex: 1;
  overflow: hidden;
}
.pl-tabs :deep(.el-tab-pane) {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.pl-code-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.pl-code-title { font-weight: 600; font-size: 14px; }
.pl-code-body {
  flex: 1;
  overflow: auto;
  background: #1e1e1e;
  border-radius: 8px;
  padding: 16px;
}
.pl-code-body pre {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}
.pl-code-body code {
  font-family: 'Cascadia Code', 'Consolas', monospace;
}

.pl-flow-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.pl-flow-hint { font-size: 12px; color: #909399; }
.pl-flow-canvas {
  flex: 1;
  min-height: 400px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  overflow: hidden;
  background: #fafbfc;
}
.pl-vue-flow {
  width: 100%;
  height: 100%;
}

.pl-detail-side {
  width: 260px;
  flex-shrink: 0;
  overflow-y: auto;
}

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
.exec-success .exec-status { color: #67c23a; }
.exec-failed .exec-status { color: #f56c6c; }

.run-result {
  margin-top: 16px;
  padding: 12px;
  border-radius: 8px;
  font-size: 13px;
}
.run-result.success { background: #f0f9eb; border: 1px solid #e1f3d8; }
.run-result.failed { background: #fef0f0; border: 1px solid #fde2e2; }
.run-status { font-weight: 600; margin-bottom: 8px; }
.run-output, .run-error {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 10px;
  border-radius: 6px;
  font-size: 12px;
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
}
.run-error { color: #f56c6c; }
</style>
