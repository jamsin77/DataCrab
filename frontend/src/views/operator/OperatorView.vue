<template>
  <div class="operator-page">
    <div class="toolbar">
      <el-upload
        :show-file-list="false"
        :before-upload="handleUpload"
        accept=".py"
        :http-request="uploadOperator"
      >
        <el-button type="primary">
          <el-icon><Upload /></el-icon>
          上传Python脚本
        </el-button>
      </el-upload>
      <el-button type="success" @click="showGenerateDialog = true">
        <el-icon><MagicStick /></el-icon>
        生成算子
      </el-button>
      <el-select v-model="filterCategory" placeholder="分类筛选" clearable style="width: 160px">
        <el-option v-for="cat in categories" :key="cat" :label="cat" :value="cat" />
      </el-select>
      <el-input
        v-model="searchQuery"
        placeholder="搜索算子"
        style="width: 260px"
        clearable
        :prefix-icon="Search"
      />
    </div>

    <div class="op-grid">
      <el-card v-for="op in filteredOperators" :key="op.id" class="operator-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <span class="op-name">{{ op.display_name || op.name }}</span>
              <el-tag size="small" :type="categoryColor(op.category)">{{ op.category || '未分类' }}</el-tag>
            </div>
          </template>
          <p class="op-desc">{{ op.description || '暂无描述' }}</p>
          <div class="op-meta">
            <el-tag
              v-for="(param, idx) in (op.parameters || [])"
              :key="idx"
              size="small"
              type="info"
              effect="plain"
            >
              {{ param.name }}<span v-if="param.type">: {{ param.type }}</span>
            </el-tag>
          </div>
          <div class="op-actions">
            <el-button size="small" type="primary" plain @click="openDebug(op)">
              <el-icon><VideoPlay /></el-icon> 调试
            </el-button>
            <el-button size="small" @click="downloadOperator(op)">
              <el-icon><Download /></el-icon> 下载
            </el-button>
            <el-button size="small" type="warning" plain @click="openModifyDialog(op)">
              <el-icon><Edit /></el-icon> 修改
            </el-button>
            <el-button size="small" type="info" plain @click="openCloneDialog(op)">
              <el-icon><CopyDocument /></el-icon> 另存为
            </el-button>
            <el-button size="small" type="danger" plain @click="confirmDelete(op)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
        </el-card>
    </div>

    <el-empty v-if="filteredOperators.length === 0" description="暂无算子，请上传Python脚本" />

    <el-drawer
      v-model="debugDrawer"
      :title="debugOperator?.display_name || debugOperator?.name || '调试算子'"
      size="75%"
      destroy-on-close
    >
      <div class="debug-layout">
        <div class="debug-left">
          <div class="section-title">
            <span>Python 脚本</span>
            <el-button size="small" text type="primary" @click="saveScript" :loading="saving">
              <el-icon><Check /></el-icon> 保存修改
            </el-button>
          </div>
          <textarea
            v-model="editScript"
            class="code-editor"
            spellcheck="false"
          ></textarea>
        </div>
        <div class="debug-right">
          <div class="section-title">调试面板</div>

          <div class="func-signature">
            <code>{{ debugOperator?.function_name }}({{ signatureParams }})</code>
            <span v-if="debugOperator?.outputs?.length" class="return-type">
              → {{ debugOperator.outputs[0].type }}
            </span>
          </div>

          <div v-if="debugInputs.length" class="param-group">
            <div class="group-title">入参</div>
            <div v-for="input in debugInputs" :key="'in-' + input.name" class="param-section">
              <div class="label">
                {{ input.name }}
                <el-tag size="small" type="primary" effect="plain">{{ input.type }}</el-tag>
                <el-tag size="small" type="danger" effect="plain">必填</el-tag>
              </div>
              <el-input
                v-model="debugInputValues[input.name]"
                type="textarea"
                :rows="input.name === 'data' || input.name === 'df' ? 6 : 3"
                :placeholder="getInputPlaceholder(input)"
              />
            </div>
          </div>

          <div v-if="debugOptionalParams.length" class="param-group">
            <div class="group-title">可选参数</div>
            <div v-for="param in debugOptionalParams" :key="'opt-' + param.name" class="param-section">
              <div class="label">
                {{ param.name }}
                <el-tag size="small" type="warning" effect="plain">{{ param.type }}</el-tag>
                <el-tag size="small" effect="plain" v-if="param.default !== null && param.default !== undefined">
                  默认: {{ param.default }}
                </el-tag>
              </div>
              <el-input
                v-model="debugParamValues[param.name]"
                :placeholder="String(param.default ?? '')"
              />
            </div>
          </div>

          <div v-if="debugOperator?.outputs?.length" class="param-group">
            <div class="group-title">出参</div>
            <div class="output-info">
              <el-tag type="success" effect="plain">
                {{ debugOperator.outputs[0].name }}: {{ debugOperator.outputs[0].type }}
              </el-tag>
            </div>
          </div>

          <el-button type="primary" @click="runDebug" :loading="debugRunning" style="width: 100%">
            <el-icon><CaretRight /></el-icon> 执行调试
          </el-button>

          <div v-if="debugResult !== null" class="debug-result">
            <div class="result-header">
              <el-tag :type="debugResult.success ? 'success' : 'danger'">
                {{ debugResult.success ? '成功' : '失败' }}
              </el-tag>
              <span v-if="debugResult.execution_time_ms" class="exec-time">
                {{ debugResult.execution_time_ms }}ms
              </span>
            </div>
            <div v-if="debugResult.error" class="error-block">
              <pre>{{ debugResult.error }}</pre>
            </div>
            <div v-if="debugResult.stdout" class="stdout-block">
              <div class="label">标准输出:</div>
              <pre>{{ debugResult.stdout }}</pre>
            </div>
            <div v-if="debugResult.result !== undefined && debugResult.result !== null" class="result-block">
              <div class="label">返回结果:</div>
              <pre>{{ JSON.stringify(debugResult.result, null, 2) }}</pre>
            </div>
          </div>
        </div>
      </div>
    </el-drawer>

    <el-dialog v-model="showGenerateDialog" title="AI 生成算子" width="550px" @closed="generatePrompt = ''">
      <el-form label-width="80px">
        <el-form-item label="需求描述">
          <el-input
            v-model="generatePrompt"
            type="textarea"
            :rows="4"
            placeholder="用自然语言描述你需要什么算子，例如：按照年代筛选文物数据，支持根据数据源名称查询，返回前100条"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showGenerateDialog = false">取消</el-button>
        <el-button type="primary" @click="handleGenerate" :loading="generating">
          {{ generating ? 'AI 生成中...' : '开始生成' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showModifyDialog" title="AI 修改算子" width="550px" @closed="modifyInstruction = ''; modifyTarget = null">
      <div v-if="modifyTarget" class="modify-target-info">
        <el-tag>{{ modifyTarget.display_name || modifyTarget.name }}</el-tag>
        <span class="modify-desc">{{ modifyTarget.description || '暂无描述' }}</span>
      </div>
      <el-form label-width="80px" style="margin-top: 12px">
        <el-form-item label="修改指令">
          <el-input
            v-model="modifyInstruction"
            type="textarea"
            :rows="4"
            placeholder="你希望如何修改这个算子？例如：增加数量限制参数，默认返回50条"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showModifyDialog = false">取消</el-button>
        <el-button type="primary" @click="handleModify" :loading="modifying">
          {{ modifying ? 'AI 修改中...' : '开始修改' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showCloneDialog" title="另存为" width="450px" @closed="cloneName = ''; cloneTarget = null">
      <div v-if="cloneTarget" class="modify-target-info">
        <el-tag>{{ cloneTarget.display_name || cloneTarget.name }}</el-tag>
        <span class="modify-desc">将复制脚本和全部配置</span>
      </div>
      <el-form label-width="80px" style="margin-top: 12px">
        <el-form-item label="新名称" required>
          <el-input
            v-model="cloneName"
            placeholder="输入新算子的名称"
            @keyup.enter="handleClone"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCloneDialog = false">取消</el-button>
        <el-button type="primary" @click="handleClone" :loading="cloning" :disabled="!cloneName.trim()">
          {{ cloning ? '复制中...' : '确认复制' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { Upload, Download, Delete, VideoPlay, CaretRight, Search, Check, MagicStick, Edit, CopyDocument } from '@element-plus/icons-vue'
import api from '@/api/index'
import { ElMessage, ElMessageBox } from 'element-plus'

const operators = ref<any[]>([])
const categories = ref<string[]>([])
const filterCategory = ref('')
const searchQuery = ref('')

const filteredOperators = computed(() => {
  let list = operators.value
  if (filterCategory.value) {
    list = list.filter((o: any) => o.category === filterCategory.value)
  }
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    list = list.filter(
      (o: any) =>
        (o.name || '').toLowerCase().includes(q) ||
        (o.display_name || '').toLowerCase().includes(q) ||
        (o.description || '').toLowerCase().includes(q)
    )
  }
  return list
})

async function loadOperators() {
  try {
    operators.value = await api.get('/operators')
    categories.value = await api.get('/operators/categories')
  } catch (e: any) {
    ElMessage.error('加载算子失败')
  }
}

async function uploadOperator(options: any) {
  const formData = new FormData()
  formData.append('file', options.file)
  if (filterCategory.value) {
    formData.append('category', filterCategory.value)
  }
  try {
    const res = await api.post('/operators/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    ElMessage.success(`算子 "${res.display_name || res.name}" 创建成功`)
    await loadOperators()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '上传失败')
  }
}

function handleUpload(file: any) {
  const isPython = file.name.toLowerCase().endsWith('.py')
  if (!isPython) {
    ElMessage.error('只能上传 .py 文件')
    return false
  }
  return true
}

function downloadOperator(op: any) {
  const token = localStorage.getItem('access_token')
  const url = `/api/v1/operators/download/${op.id}`
  if (token) {
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.blob())
      .then((blob) => {
        const blobUrl = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = blobUrl
        a.download = op.script_filename || `${op.name}.py`
        a.click()
        URL.revokeObjectURL(blobUrl)
      })
  }
}

async function confirmDelete(op: any) {
  try {
    await ElMessageBox.confirm(
      `确定要删除算子 "${op.display_name || op.name}" 吗？`,
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    await api.delete(`/operators/${op.id}`)
    ElMessage.success('删除成功')
    await loadOperators()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e.response?.data?.detail || '删除失败')
    }
  }
}

const debugDrawer = ref(false)
const debugOperator = ref<any>(null)
const editScript = ref('')
const debugInputValues = reactive<Record<string, string>>({})
const debugParamValues = reactive<Record<string, string>>({})
const debugRunning = ref(false)
const debugResult = ref<any>(null)
const saving = ref(false)

const debugInputs = computed(() => {
  return (debugOperator.value?.inputs || []) as any[]
})

const debugOptionalParams = computed(() => {
  const allParams = (debugOperator.value?.parameters || []) as any[]
  const inputNames = new Set(debugInputs.value.map((i: any) => i.name))
  return allParams.filter((p: any) => !inputNames.has(p.name))
})

const signatureParams = computed(() => {
  const allParams = (debugOperator.value?.parameters || []) as any[]
  return allParams
    .map((p: any) => {
      let sig = p.name
      if (p.type && p.type !== 'any') sig += `: ${p.type}`
      if (p.default !== null && p.default !== undefined) sig += ` = ${p.default}`
      return sig
    })
    .join(', ')
})

function getInputPlaceholder(input: any) {
  const t = input.type || 'any'
  if (t === 'DataFrame' || t === 'list') return '输入 JSON 数组，如 [{"col": 1}]'
  if (t === 'str') return '输入字符串'
  if (t === 'int' || t === 'float') return '输入数值'
  return '输入 JSON 数据'
}

function openDebug(op: any) {
  debugOperator.value = op
  editScript.value = op.script_content || ''

  for (const key of Object.keys(debugInputValues)) {
    delete debugInputValues[key]
  }
  for (const key of Object.keys(debugParamValues)) {
    delete debugParamValues[key]
  }

  const inputs = (op.inputs || []) as any[]
  for (const input of inputs) {
    debugInputValues[input.name] = ''
  }

  const allParams = (op.parameters || []) as any[]
  const inputNames = new Set(inputs.map((i: any) => i.name))
  for (const param of allParams) {
    if (!inputNames.has(param.name)) {
      debugParamValues[param.name] = param.default !== null && param.default !== undefined
        ? String(param.default)
        : ''
    }
  }

  debugResult.value = null
  debugDrawer.value = true
}

async function saveScript() {
  if (!debugOperator.value) return
  saving.value = true
  try {
    const res = await api.put(`/operators/${debugOperator.value.id}/script`, {
      script_content: editScript.value,
    })
    debugOperator.value = res
    ElMessage.success('脚本已保存，入参出参已重新解析')
    await loadOperators()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

function parseJsonValue(raw: string): any {
  if (!raw || raw.trim() === '') return null
  const trimmed = raw.trim()
  try {
    return JSON.parse(trimmed)
  } catch {
    if (trimmed === 'True' || trimmed === 'true') return true
    if (trimmed === 'False' || trimmed === 'false') return false
    if (trimmed === 'None' || trimmed === 'null') return null
    if (/^-?\d+$/.test(trimmed)) return parseInt(trimmed, 10)
    if (/^-?\d+\.\d+$/.test(trimmed)) return parseFloat(trimmed)
    return trimmed
  }
}

async function runDebug() {
  if (!debugOperator.value) return
  debugRunning.value = true
  debugResult.value = null

  const inputs = debugInputs.value
  const optParams = debugOptionalParams.value

  let testData: any = null
  const parameters: Record<string, any> = {}

  if (inputs.length > 0) {
    const firstInput = inputs[0]
    const raw = debugInputValues[firstInput.name] || ''
    testData = parseJsonValue(raw)
  }

  for (let i = 1; i < inputs.length; i++) {
    const input = inputs[i]
    const raw = debugInputValues[input.name] || ''
    parameters[input.name] = parseJsonValue(raw)
  }

  for (const param of optParams) {
    const raw = debugParamValues[param.name] || ''
    if (raw !== '') {
      parameters[param.name] = parseJsonValue(raw)
    } else if (param.default !== null && param.default !== undefined) {
      parameters[param.name] = parseJsonValue(String(param.default))
    }
  }

  try {
    const res = await api.post(`/operators/${debugOperator.value.id}/debug`, {
      parameters,
      test_data: testData,
    })
    debugResult.value = res
  } catch (e: any) {
    debugResult.value = {
      success: false,
      error: e.response?.data?.detail || String(e),
    }
  } finally {
    debugRunning.value = false
  }
}

function categoryColor(cat: string) {
  const map: Record<string, string> = {
    transform: 'primary',
    aggregate: 'success',
    join: 'warning',
    clean: 'info',
    analysis: 'danger',
    custom: '',
  }
  return map[cat] || ''
}

const showGenerateDialog = ref(false)
const generatePrompt = ref('')
const generating = ref(false)

const showModifyDialog = ref(false)
const modifyTarget = ref<any>(null)
const modifyInstruction = ref('')
const modifying = ref(false)

async function handleGenerate() {
  if (!generatePrompt.value.trim()) {
    ElMessage.warning('请输入需求描述')
    return
  }
  generating.value = true
  try {
    const res = await api.post('/operators/generate', { prompt: generatePrompt.value.trim() }, { timeout: 120000 })
    ElMessage.success(`算子 "${res.display_name || res.name}" 已生成`)
    showGenerateDialog.value = false
    generatePrompt.value = ''
    await loadOperators()
    setTimeout(() => openDebug(res), 300)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '生成失败')
  } finally {
    generating.value = false
  }
}

function openModifyDialog(op: any) {
  modifyTarget.value = op
  modifyInstruction.value = ''
  showModifyDialog.value = true
}

async function handleModify() {
  if (!modifyInstruction.value.trim()) {
    ElMessage.warning('请输入修改指令')
    return
  }
  if (!modifyTarget.value) return
  modifying.value = true
  try {
    const res = await api.post(`/operators/${modifyTarget.value.id}/modify`, {
      instruction: modifyInstruction.value.trim(),
    }, { timeout: 120000 })
    ElMessage.success(`算子 "${res.display_name || res.name}" 已修改`)
    showModifyDialog.value = false
    modifyInstruction.value = ''
    modifyTarget.value = null
    await loadOperators()
    setTimeout(() => openDebug(res), 300)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '修改失败')
  } finally {
    modifying.value = false
  }
}

const showCloneDialog = ref(false)
const cloneTarget = ref<any>(null)
const cloneName = ref('')
const cloning = ref(false)

function openCloneDialog(op: any) {
  cloneTarget.value = op
  cloneName.value = (op.display_name || op.name) + ' (副本)'
  showCloneDialog.value = true
}

async function handleClone() {
  if (!cloneName.value.trim()) {
    ElMessage.warning('请输入新名称')
    return
  }
  if (!cloneTarget.value) return
  cloning.value = true
  try {
    const res = await api.post(`/operators/${cloneTarget.value.id}/clone`, {
      name: cloneName.value.trim(),
    })
    ElMessage.success(`算子 "${res.display_name || res.name}" 复制成功`)
    showCloneDialog.value = false
    cloneName.value = ''
    cloneTarget.value = null
    await loadOperators()
    setTimeout(() => openDebug(res), 300)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '复制失败')
  } finally {
    cloning.value = false
  }
}

onMounted(loadOperators)
</script>

<style lang="scss" scoped>
.operator-page {
  padding: 20px;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  align-items: center;
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

  :deep(.el-card__header) {
    flex-shrink: 0;
  }

  :deep(.el-card__body) {
    flex: 1;
    display: flex;
    flex-direction: column;
  }

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
  }
  .op-meta {
    margin: 8px 0;
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    min-height: 26px;
    max-height: 56px;
    overflow: hidden;
  }
  .op-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: auto;
    padding-top: 12px;
  }
}

.debug-layout {
  display: flex;
  gap: 16px;
  height: calc(100vh - 80px);
}

.debug-left {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.debug-right {
  width: 380px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
}

.section-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 8px;
  color: #303133;
}

.func-signature {
  background: #f0f5ff;
  border: 1px solid #d6e4ff;
  border-radius: 6px;
  padding: 10px 14px;
  margin-bottom: 4px;
  code {
    font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
    font-size: 13px;
    color: #1d39c4;
  }
  .return-type {
    font-size: 12px;
    color: #52c41a;
    margin-left: 8px;
  }
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

.output-info {
  padding: 8px 0;
}

.code-editor {
  flex: 1;
  width: 100%;
  min-height: 300px;
  background: #1e1e1e;
  color: #d4d4d4;
  border: 1px solid #333;
  border-radius: 6px;
  padding: 12px;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
  resize: none;
  outline: none;
  tab-size: 4;

  &:focus {
    border-color: #409eff;
  }
}

.param-section {
  .label {
    font-size: 13px;
    color: #606266;
    margin-bottom: 4px;
  }
}

.debug-result {
  margin-top: 8px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 12px;
  background: #fafafa;

  .result-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 8px;
  }

  .exec-time {
    font-size: 12px;
    color: #909399;
  }

  .error-block {
    background: #fef0f0;
    border: 1px solid #fde2e2;
    border-radius: 4px;
    padding: 8px;
    margin-top: 8px;
    pre {
      color: #f56c6c;
      font-size: 12px;
      white-space: pre-wrap;
      word-break: break-all;
      margin: 0;
    }
  }

  .stdout-block {
    background: #f0f9eb;
    border: 1px solid #e1f3d8;
    border-radius: 4px;
    padding: 8px;
    margin-top: 8px;
    pre {
      color: #67c23a;
      font-size: 12px;
      white-space: pre-wrap;
      margin: 0;
    }
  }

  .result-block {
    background: #ecf5ff;
    border: 1px solid #d9ecff;
    border-radius: 4px;
    padding: 8px;
    margin-top: 8px;
    pre {
      color: #409eff;
      font-size: 12px;
      white-space: pre-wrap;
      word-break: break-all;
      margin: 0;
      max-height: 300px;
      overflow-y: auto;
    }
  }
}
</style>

<style lang="scss">
.modify-target-info {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 10px 14px;
  background: #f5f7fa;
  border-radius: 6px;
  .modify-desc {
    font-size: 13px;
    color: #909399;
    overflow: hidden;
    word-break: break-all;
    line-height: 1.5;
    max-height: 120px;
    overflow-y: auto;
  }
}
</style>