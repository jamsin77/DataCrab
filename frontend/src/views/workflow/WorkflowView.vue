<template>
  <div class="workflow-view">
    <template v-if="!editingWorkflow">
      <div class="wf-toolbar">
        <div class="toolbar-left">
          <el-button type="primary" @click="showCreateDialog = true">新建流程</el-button>
          <el-dropdown @command="handleFromSkill">
            <el-button>从Skill转换 <i class="el-icon-arrow-down el-icon--right"></i></el-button>
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
          <el-select v-model="engineFilter" placeholder="引擎筛选" clearable size="small" style="width:120px" @change="loadWorkflows">
            <el-option label="本地" value="local" />
            <el-option label="Prefect" value="prefect" />
          </el-select>
          <el-input v-model="searchText" placeholder="搜索流程..." size="small" style="width:200px" clearable @input="loadWorkflows" />
        </div>
      </div>

      <div class="wf-grid" v-if="workflows.length">
        <el-card v-for="wf in workflows" :key="wf.id" class="wf-card" shadow="hover">
          <div class="wf-card-header">
            <span class="wf-card-name">{{ wf.display_name || wf.name }}</span>
            <el-tag size="small" :type="wf.engine === 'local' ? 'info' : 'success'">{{ wf.engine }}</el-tag>
          </div>
          <div class="wf-card-desc">{{ wf.description || '暂无描述' }}</div>
          <div class="wf-card-meta">
            <span>{{ (wf.nodes || []).length }} 个节点</span>
          </div>
          <div class="wf-card-actions">
            <el-button size="small" type="primary" text @click="editWorkflow(wf)">编辑</el-button>
            <el-button size="small" type="success" text @click="runWorkflow(wf)">运行</el-button>
            <el-button size="small" text @click="cloneWorkflow(wf)">复制</el-button>
            <el-button size="small" type="danger" text @click="deleteWorkflow(wf)">删除</el-button>
          </div>
        </el-card>
      </div>
      <el-empty v-else description="暂无流程" />
    </template>

    <template v-else>
      <div class="wf-editor">
        <div class="wf-editor-topbar">
          <el-button size="small" @click="closeEditor">返回列表</el-button>
          <span class="wf-editor-title">{{ editingWorkflow.display_name || editingWorkflow.name }}</span>
          <div class="wf-editor-topbar-right">
            <el-button size="small" type="success" @click="runWorkflow(editingWorkflow)">运行</el-button>
            <el-button size="small" type="primary" @click="saveWorkflow">保存</el-button>
          </div>
        </div>
        <div class="wf-editor-body">
          <div class="wf-node-palette">
            <div class="palette-title">节点面板</div>
            <div class="palette-item" draggable="true" @dragstart="onDragStart($event, 'datasource')">
              <span class="palette-icon" style="color:#67C23A">📥</span> 数据读取
            </div>
            <div class="palette-item" draggable="true" @dragstart="onDragStart($event, 'skill')">
              <span class="palette-icon" style="color:#409EFF">⚡</span> 技能节点
            </div>
            <div class="palette-item" draggable="true" @dragstart="onDragStart($event, 'writer')">
              <span class="palette-icon" style="color:#E6A23C">📤</span> 数据写入
            </div>
            <div class="palette-item" draggable="true" @dragstart="onDragStart($event, 'condition')">
              <span class="palette-icon" style="color:#F56C6C">🔀</span> 条件分支
            </div>
          </div>
          <div class="wf-canvas" @drop="onDrop" @dragover.prevent>
            <VueFlow v-model:nodes="flowNodes" v-model:edges="flowEdges" :default-viewport="{ zoom: 1, x: 0, y: 0 }" :min-zoom="0.3" :max-zoom="2" fit-view-on-init @node-click="onNodeClick" @connect="onConnect">
              <Background />
              <Controls />
              <template #node-skill="skillNodeProps">
                <div class="flow-node skill-node" :class="{ 'node-selected': selectedNodeId === skillNodeProps.id }">
                  <div class="flow-node-header">⚡ {{ skillNodeProps.data?.label || '技能' }}</div>
                  <Handle type="target" :position="Position.Left" />
                  <Handle type="source" :position="Position.Right" />
                </div>
              </template>
              <template #node-datasource="dsNodeProps">
                <div class="flow-node ds-node" :class="{ 'node-selected': selectedNodeId === dsNodeProps.id }">
                  <div class="flow-node-header">📥 {{ dsNodeProps.data?.label || '数据读取' }}</div>
                  <Handle type="source" :position="Position.Right" />
                </div>
              </template>
              <template #node-writer="writerNodeProps">
                <div class="flow-node writer-node" :class="{ 'node-selected': selectedNodeId === writerNodeProps.id }">
                  <div class="flow-node-header">📤 {{ writerNodeProps.data?.label || '数据写入' }}</div>
                  <Handle type="target" :position="Position.Left" />
                </div>
              </template>
              <template #node-condition="condNodeProps">
                <div class="flow-node cond-node" :class="{ 'node-selected': selectedNodeId === condNodeProps.id }">
                  <div class="flow-node-header">🔀 {{ condNodeProps.data?.label || '条件' }}</div>
                  <Handle type="target" :position="Position.Left" />
                  <Handle type="source" :position="Position.Right" id="yes" />
                  <Handle type="source" :position="Position.Bottom" id="no" />
                </div>
              </template>
            </VueFlow>
          </div>
          <div class="wf-props-panel" v-if="selectedNode">
            <div class="props-title">节点属性</div>
            <el-form label-width="80px" size="small">
              <el-form-item label="名称">
                <el-input v-model="selectedNode.data.label" @change="syncNodeToModel" />
              </el-form-item>
              <el-form-item label="类型">
                <el-tag size="small">{{ selectedNode.type }}</el-tag>
              </el-form-item>
              <el-form-item label="Skill ID" v-if="selectedNode.type === 'skill'">
                <el-input v-model="selectedNode.data.skill_id" @change="syncNodeToModel" />
              </el-form-item>
              <el-form-item label="重试次数">
                <el-input-number v-model="selectedNode.data.retry" :min="0" :max="10" @change="syncNodeToModel" />
              </el-form-item>
              <el-form-item label="超时(秒)">
                <el-input-number v-model="selectedNode.data.timeout" :min="10" :max="3600" :step="30" @change="syncNodeToModel" />
              </el-form-item>
              <el-form-item>
                <el-button type="danger" size="small" @click="removeSelectedNode">删除节点</el-button>
              </el-form-item>
            </el-form>
          </div>
        </div>
      </div>
    </template>

    <el-dialog v-model="showCreateDialog" title="新建流程" width="450px">
      <el-form label-width="80px">
        <el-form-item label="名称"><el-input v-model="createForm.name" /></el-form-item>
        <el-form-item label="显示名"><el-input v-model="createForm.display_name" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="createForm.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="引擎">
          <el-select v-model="createForm.engine">
            <el-option label="本地执行" value="local" />
            <el-option label="Prefect" value="prefect" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="createWorkflow">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showRunDialog" title="运行流程" width="500px">
      <el-form label-width="80px">
        <el-form-item label="输入参数">
          <el-input v-model="runInputs" type="textarea" :rows="6" placeholder='{"datasource": "文物", "tables": ["Sheet1"]}' />
        </el-form-item>
      </el-form>
      <div v-if="runResult" class="run-result">
        <div>状态: <el-tag :type="runResult.status === 'success' ? 'success' : 'danger'" size="small">{{ runResult.status }}</el-tag></div>
        <div v-if="runResult.duration_ms">耗时: {{ (runResult.duration_ms / 1000).toFixed(1) }}s</div>
        <div v-if="runResult.error_message" style="color:#F56C6C">错误: {{ runResult.error_message }}</div>
      </div>
      <template #footer>
        <el-button @click="showRunDialog = false">关闭</el-button>
        <el-button type="primary" :loading="runLoading" @click="doRunWorkflow">运行</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { VueFlow, Position, Handle } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import { ElMessage, ElMessageBox } from 'element-plus'

const api = {
  get: async (url: string) => {
    const token = localStorage.getItem('access_token')
    const resp = await fetch(`/api/v1${url}`, { headers: { Authorization: `Bearer ${token}` } })
    if (!resp.ok) throw new Error(await resp.text())
    return resp.json()
  },
  post: async (url: string, body?: any) => {
    const token = localStorage.getItem('access_token')
    const resp = await fetch(`/api/v1${url}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: body ? JSON.stringify(body) : undefined,
    })
    if (!resp.ok) throw new Error(await resp.text())
    return resp.json()
  },
  put: async (url: string, body: any) => {
    const token = localStorage.getItem('access_token')
    const resp = await fetch(`/api/v1${url}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(body),
    })
    if (!resp.ok) throw new Error(await resp.text())
    return resp.json()
  },
  del: async (url: string) => {
    const token = localStorage.getItem('access_token')
    const resp = await fetch(`/api/v1${url}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!resp.ok) throw new Error(await resp.text())
    return resp.json()
  },
}

const workflows = ref<any[]>([])
const skills = ref<any[]>([])
const engineFilter = ref('')
const searchText = ref('')
const editingWorkflow = ref<any>(null)
const selectedNodeId = ref<string | null>(null)
const showCreateDialog = ref(false)
const showRunDialog = ref(false)
const runInputs = ref('{}')
const runResult = ref<any>(null)
const runLoading = ref(false)
const runningWorkflowId = ref<string>('')

const createForm = reactive({
  name: '',
  display_name: '',
  description: '',
  engine: 'local',
})

const flowNodes = ref<any[]>([])
const flowEdges = ref<any[]>([])

const selectedNode = computed(() => {
  if (!selectedNodeId.value) return null
  return flowNodes.value.find((n: any) => n.id === selectedNodeId.value)
})

onMounted(() => {
  loadWorkflows()
  loadSkills()
})

async function loadWorkflows() {
  try {
    let url = '/workflows'
    const params: string[] = []
    if (engineFilter.value) params.push(`engine=${engineFilter.value}`)
    if (searchText.value) params.push(`search=${encodeURIComponent(searchText.value)}`)
    if (params.length) url += '?' + params.join('&')
    workflows.value = await api.get(url)
  } catch (e: any) {
    ElMessage.error('加载流程失败')
  }
}

async function loadSkills() {
  try {
    skills.value = await api.get('/skills')
  } catch {}
}

async function handleFromSkill(skillId: string) {
  try {
    const wf = await api.post(`/workflows/from-skill/${skillId}`)
    ElMessage.success('流程已创建')
    await loadWorkflows()
    editWorkflow(wf)
  } catch (e: any) {
    ElMessage.error('转换失败: ' + (e.message || '未知错误'))
  }
}

async function createWorkflow() {
  if (!createForm.name) { ElMessage.warning('请输入名称'); return }
  try {
    const wf = await api.post('/workflows', {
      name: createForm.name,
      display_name: createForm.display_name || createForm.name,
      description: createForm.description,
      engine: createForm.engine,
      nodes: [],
      edges: [],
    })
    showCreateDialog.value = false
    createForm.name = ''
    createForm.display_name = ''
    createForm.description = ''
    ElMessage.success('流程已创建')
    await loadWorkflows()
    editWorkflow(wf)
  } catch (e: any) {
    ElMessage.error('创建失败: ' + (e.message || ''))
  }
}

function editWorkflow(wf: any) {
  editingWorkflow.value = { ...wf }
  selectedNodeId.value = null
  flowNodes.value = (wf.nodes || []).map((n: any) => ({
    id: n.id,
    type: n.type === 'skill' ? (n.skill_id?.startsWith('__builtin') ? n.skill_id === '__builtin_data_reader' ? 'datasource' : n.skill_id === '__builtin_data_writer' ? 'writer' : 'skill' : 'skill') : n.type,
    position: n.position || { x: 0, y: 0 },
    data: { label: n.name || n.id, ...n },
  }))
  flowEdges.value = (wf.edges || []).map((e: any) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: e.source_port,
    targetHandle: e.target_port,
    animated: true,
    style: { stroke: '#409EFF' },
  }))
}

function closeEditor() {
  editingWorkflow.value = null
  selectedNodeId.value = null
  loadWorkflows()
}

async function saveWorkflow() {
  if (!editingWorkflow.value) return
  const nodes = flowNodes.value.map((n: any) => ({
    id: n.id,
    type: n.data?.type || n.type === 'datasource' ? 'skill' : n.type === 'writer' ? 'skill' : n.type,
    skill_id: n.data?.skill_id || (n.type === 'datasource' ? '__builtin_data_reader' : n.type === 'writer' ? '__builtin_data_writer' : n.data?.skill_id),
    name: n.data?.label || n.id,
    config: n.data?.config || { parameters: {}, parameter_mappings: {} },
    position: n.position,
    retry: n.data?.retry ?? 0,
    timeout: n.data?.timeout ?? 300,
  }))
  const edges = flowEdges.value.map((e: any) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    source_port: e.sourceHandle,
    target_port: e.targetHandle,
  }))
  try {
    await api.put(`/workflows/${editingWorkflow.value.id}`, { nodes, edges })
    ElMessage.success('已保存')
  } catch (e: any) {
    ElMessage.error('保存失败: ' + (e.message || ''))
  }
}

function runWorkflow(wf: any) {
  runningWorkflowId.value = wf.id
  runInputs.value = '{}'
  runResult.value = null
  showRunDialog.value = true
}

async function doRunWorkflow() {
  runLoading.value = true
  runResult.value = null
  let inputs = {}
  try { inputs = JSON.parse(runInputs.value || '{}') } catch { inputs = {} }
  try {
    const result = await api.post(`/workflows/${runningWorkflowId.value}/run`, { inputs })
    runResult.value = result
    if (result.status === 'success') ElMessage.success('执行成功')
    else ElMessage.error('执行失败')
  } catch (e: any) {
    runResult.value = { status: 'failed', error_message: e.message }
    ElMessage.error('执行异常')
  } finally {
    runLoading.value = false
  }
}

async function cloneWorkflow(wf: any) {
  try {
    await api.post(`/workflows/${wf.id}/clone`)
    ElMessage.success('已复制')
    await loadWorkflows()
  } catch (e: any) {
    ElMessage.error('复制失败')
  }
}

async function deleteWorkflow(wf: any) {
  try {
    await ElMessageBox.confirm(`确定删除流程 "${wf.display_name || wf.name}"？`, '确认删除', { type: 'warning' })
    await api.del(`/workflows/${wf.id}`)
    ElMessage.success('已删除')
    await loadWorkflows()
  } catch {}
}

function onDragStart(event: DragEvent, nodeType: string) {
  event.dataTransfer?.setData('application/vueflow', nodeType)
  event.dataTransfer!.effectAllowed = 'move'
}

function onDrop(event: DragEvent) {
  const nodeType = event.dataTransfer?.getData('application/vueflow')
  if (!nodeType) return
  const id = 'node_' + Date.now()
  const labels: Record<string, string> = { datasource: '数据读取', skill: '技能节点', writer: '数据写入', condition: '条件分支' }
  const skillIds: Record<string, string> = { datasource: '__builtin_data_reader', writer: '__builtin_data_writer' }
  flowNodes.value.push({
    id,
    type: nodeType,
    position: { x: event.offsetX - 100, y: event.offsetY - 20 },
    data: { label: labels[nodeType] || nodeType, skill_id: skillIds[nodeType] || '', type: nodeType, config: { parameters: {}, parameter_mappings: {} }, retry: 0, timeout: 300 },
  })
}

function onNodeClick(event: any) {
  selectedNodeId.value = event.node?.id || null
}

function onConnect(params: any) {
  flowEdges.value.push({
    id: 'e_' + Date.now(),
    source: params.source,
    target: params.target,
    sourceHandle: params.sourceHandle,
    targetHandle: params.targetHandle,
    animated: true,
    style: { stroke: '#409EFF' },
  })
}

function syncNodeToModel() {}

function removeSelectedNode() {
  if (!selectedNodeId.value) return
  flowNodes.value = flowNodes.value.filter((n: any) => n.id !== selectedNodeId.value)
  flowEdges.value = flowEdges.value.filter((e: any) => e.source !== selectedNodeId.value && e.target !== selectedNodeId.value)
  selectedNodeId.value = null
}
</script>

<style scoped>
.workflow-view { padding: 20px; height: calc(100vh - 60px); overflow-y: auto; }
.wf-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
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
.wf-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.wf-card { cursor: pointer; transition: transform 0.2s; }
.wf-card:hover { transform: translateY(-2px); }
.wf-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.wf-card-name { font-weight: 600; font-size: 15px; }
.wf-card-desc { font-size: 13px; color: #909399; margin-bottom: 8px; min-height: 36px; }
.wf-card-meta { font-size: 12px; color: #b0b0b0; margin-bottom: 8px; }
.wf-card-actions {
  display: flex;
  gap: 8px;
  border-top: 1px solid #ebeef5;
  padding-top: 8px;
  align-items: center;
}
.wf-editor { display: flex; flex-direction: column; height: calc(100vh - 80px); }
.wf-editor-topbar { display: flex; align-items: center; gap: 12px; padding: 8px 16px; background: #fff; border-bottom: 1px solid #e4e7ed; }
.wf-editor-title { font-weight: 600; font-size: 16px; flex: 1; }
.wf-editor-topbar-right { display: flex; gap: 8px; }
.wf-editor-body { display: flex; flex: 1; overflow: hidden; }
.wf-node-palette { width: 180px; background: #fff; border-right: 1px solid #e4e7ed; padding: 12px; }
.palette-title { font-weight: 600; font-size: 13px; margin-bottom: 12px; color: #606266; }
.palette-item { padding: 8px 10px; margin-bottom: 6px; border: 1px solid #e4e7ed; border-radius: 6px; cursor: grab; font-size: 13px; display: flex; align-items: center; gap: 6px; transition: background 0.15s; }
.palette-item:hover { background: #f0f7ff; border-color: #b3d8ff; }
.palette-icon { font-size: 16px; }
.wf-canvas { flex: 1; background: #f5f7fa; position: relative; }
.wf-props-panel { width: 260px; background: #fff; border-left: 1px solid #e4e7ed; padding: 12px; overflow-y: auto; }
.props-title { font-weight: 600; font-size: 13px; margin-bottom: 12px; color: #606266; }
.flow-node { padding: 8px 16px; border-radius: 6px; min-width: 120px; font-size: 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.1); }
.flow-node-header { font-weight: 600; }
.skill-node { background: #ecf5ff; border: 2px solid #409EFF; }
.ds-node { background: #f0f9eb; border: 2px solid #67C23A; }
.writer-node { background: #fdf6ec; border: 2px solid #E6A23C; }
.cond-node { background: #fef0f0; border: 2px solid #F56C6C; }
.node-selected { box-shadow: 0 0 0 3px rgba(64,158,255,0.4); }
.run-result { margin-top: 12px; padding: 12px; background: #f5f7fa; border-radius: 6px; font-size: 13px; }
.run-result div { margin-bottom: 4px; }
</style>
