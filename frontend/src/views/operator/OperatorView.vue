<template>
  <div class="operator-page">
    <div class="toolbar">
      <div class="toolbar-left">
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
      </div>
      <div class="toolbar-right">
        <el-select v-model="filterCategory" placeholder="分类筛选" clearable style="width: 140px">
          <el-option v-for="cat in categories" :key="cat" :label="cat" :value="cat" />
        </el-select>
        <el-input
          v-model="searchQuery"
          placeholder="搜索算子"
          style="width: 220px"
          clearable
          :prefix-icon="Search"
        />
      </div>
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
            <div class="op-actions-row">
              <el-button size="small" type="primary" @click="openModifyDialog(op)">
                <el-icon><Edit /></el-icon> 修改
              </el-button>
              <el-button size="small" type="success" plain @click="openDebug(op)">
                <el-icon><VideoPlay /></el-icon> 调试
              </el-button>
              <el-button size="small" @click="openCloneDialog(op)">
                <el-icon><CopyDocument /></el-icon> 另存
              </el-button>
              <el-button size="small" @click="downloadOperator(op)">
                <el-icon><Download /></el-icon> 下载
              </el-button>
            </div>
            <div class="op-actions-row">
              <el-button size="small" type="danger" plain @click="confirmDelete(op)">
                <el-icon><Delete /></el-icon> 删除
              </el-button>
            </div>
          </div>
        </el-card>
    </div>

    <el-empty v-if="filteredOperators.length === 0" description="暂无算子，请上传Python脚本" />

    <el-dialog
      v-model="debugDrawer"
      :title="'调试: ' + (debugOperator?.display_name || debugOperator?.name || '')"
      width="95%"
      top="2vh"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :before-close="handleDebugBeforeClose"
      @closed="resetDebug"
    >
      <div v-if="debugOperator" class="debug-layout">
        <div class="debug-left">
          <div class="debug-section-title">
            <span>算子参数</span>
            <el-button size="small" text type="primary" @click="refreshOpScript" :loading="saving">
              <el-icon><Refresh /></el-icon> 刷新脚本
            </el-button>
          </div>

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

          <el-button type="primary" @click="runDebug" :loading="debugRunning" style="width: 100%; margin-top: 8px">
            <el-icon><CaretRight /></el-icon> 执行调试
          </el-button>
        </div>

        <div class="debug-right">
          <div class="debug-chat-header">
            <el-icon><ChatDotRound /></el-icon>
            <span>AI 代码助手</span>
          </div>
          <div class="debug-message-list" ref="opMsgListRef" @scroll="onOpListScroll">
            <div v-if="opMessages.length === 0" class="debug-empty">
              <p>输入消息调试算子代码，例如"帮我修一下这个报错"、"优化这段代码"</p>
            </div>
            <div
              v-for="(msg, idx) in opMessages"
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
                  <div v-if="msg.executingMsg" class="debug-msg-executing">
                    <el-icon class="thinking-spin"><Loading /></el-icon>
                    <span>{{ msg.executingMsg }}</span>
                  </div>
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
                        <el-collapse-item title="标准输出">
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
            <div v-if="(opStreaming || debugRunning) && !opMessages.length" class="debug-message assistant">
              <div class="debug-msg-avatar"><el-avatar :size="32" style="background:#409eff">AI</el-avatar></div>
              <div class="debug-msg-body">
                <div class="typing-indicator"><span></span><span></span><span></span></div>
              </div>
            </div>
          </div>

          <div class="debug-input-area">
            <el-input
              v-model="opInput"
              type="textarea"
              :rows="2"
              :autosize="{ minRows: 1, maxRows: 4 }"
              placeholder="输入调试指令... (Enter发送，↑↓切换历史)"
              @keydown="handleOpKeyDown"
              :disabled="opStreaming"
            />
            <el-button
              v-if="opStreaming"
              type="danger"
              circle
              @click="stopOpGeneration"
            >
              <el-icon><VideoPause /></el-icon>
            </el-button>
            <el-button
              v-else
              type="primary"
              circle
              :disabled="!opInput.trim()"
              @click="handleOpSend"
            >
              <el-icon><Promotion /></el-icon>
            </el-button>
          </div>
        </div>
      </div>
    </el-dialog>

    <el-dialog v-model="showGenerateDialog" title="AI 生成算子" width="650px" :close-on-press-escape="false" @closed="onGenerateDialogClosed">
      <el-form label-width="80px">
        <el-form-item label="需求描述">
          <el-input
            v-model="generatePrompt"
            type="textarea"
            :rows="4"
            placeholder="用自然语言描述你需要什么算子，例如：按照年代筛选文物数据，支持根据数据源名称查询，返回前100条（↑↓ 切换历史输入）"
            @keydown="onGenerateHistoryKey"
          />
        </el-form-item>
      </el-form>
      <div v-if="generateThinking || generateContent || generatePhase" class="ai-process-box">
        <div v-if="generatePhase" class="ai-phase">
          <el-icon class="phase-spin"><Loading /></el-icon>
          <span>{{ generatePhase }}</span>
        </div>
        <div v-if="generateThinking" class="ai-thinking">
          <div class="thinking-header">
            <el-icon><Cpu /></el-icon>
            <span>推理过程</span>
          </div>
          <div class="thinking-body">{{ generateThinking }}</div>
        </div>
        <div v-if="generateContent" class="ai-code-preview">
          <div class="code-preview-header">
            <el-icon><Document /></el-icon>
            <span>生成的代码</span>
          </div>
          <pre class="code-preview-body">{{ generateContent }}</pre>
        </div>
      </div>
      <template #footer>
        <el-button @click="showGenerateDialog = false" :disabled="generating">取消</el-button>
        <el-button
          v-if="generating"
          type="danger"
          @click="stopGenerate"
        >
          <el-icon><VideoPause /></el-icon> 停止
        </el-button>
        <el-button type="primary" @click="handleGenerate" :loading="generating" :disabled="generating">
          {{ generating ? 'AI 生成中...' : '开始生成' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showModifyDialog" title="AI 修改算子" width="650px" :close-on-press-escape="false" @closed="onModifyDialogClosed">
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
            placeholder="你希望如何修改这个算子？例如：增加数量限制参数，默认返回50条（↑↓ 切换历史输入）"
            @keydown="onModifyHistoryKey"
          />
        </el-form-item>
      </el-form>
      <div v-if="modifyThinking || modifyContent || modifyPhase" class="ai-process-box">
        <div v-if="modifyPhase" class="ai-phase">
          <el-icon class="phase-spin"><Loading /></el-icon>
          <span>{{ modifyPhase }}</span>
        </div>
        <div v-if="modifyThinking" class="ai-thinking">
          <div class="thinking-header">
            <el-icon><Cpu /></el-icon>
            <span>推理过程</span>
          </div>
          <div class="thinking-body">{{ modifyThinking }}</div>
        </div>
        <div v-if="modifyContent" class="ai-code-preview">
          <div class="code-preview-header">
            <el-icon><Document /></el-icon>
            <span>修改后的代码</span>
          </div>
          <pre class="code-preview-body">{{ modifyContent }}</pre>
        </div>
      </div>
      <template #footer>
        <el-button @click="showModifyDialog = false" :disabled="modifying">取消</el-button>
        <el-button
          v-if="modifying"
          type="danger"
          @click="stopModify"
        >
          <el-icon><VideoPause /></el-icon> 停止
        </el-button>
        <el-button type="primary" @click="handleModify" :loading="modifying" :disabled="modifying">
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
import { ref, reactive, computed, onMounted, nextTick, watch, type Ref } from 'vue'
import { Upload, Download, Delete, VideoPlay, CaretRight, Search, Check, MagicStick, Edit, CopyDocument, VideoPause, Loading, Document, Cpu, ChatDotRound, Promotion, Refresh } from '@element-plus/icons-vue'
import api from '@/api/index'
import { ElMessage, ElMessageBox } from 'element-plus'
import markdownIt from 'markdown-it'

const md = markdownIt({ html: false, breaks: true, linkify: true })
function renderMarkdown(text: string) {
  return md.render(text || '')
}

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
const debugInputValues = reactive<Record<string, string>>({})
const debugParamValues = reactive<Record<string, string>>({})
const debugRunning = ref(false)
const saving = ref(false)

interface OpChatMessage {
  role: 'user' | 'assistant'
  content: string
  thinking?: string
  thinkingOpen?: boolean
  scriptUpdated?: string
  runResult?: any
  model?: string
  executingMsg?: string
}
const opMessages = ref<OpChatMessage[]>([])
const opInput = ref('')
const opStreaming = ref(false)
let opAbortController: AbortController | null = null
const opMsgListRef = ref<HTMLElement | null>(null)
const opPinnedToBottom = ref(true)

function scrollOpToBottom(force = false) {
  const el = opMsgListRef.value
  if (!el) return
  if (!force && !opPinnedToBottom.value) return
  el.scrollTop = el.scrollHeight
}

function onOpListScroll() {
  const el = opMsgListRef.value
  if (!el) return
  opPinnedToBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

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
  const hint = '（↑↓ 切换历史输入）'
  const t = input.type || 'any'
  if (t === 'DataFrame' || t === 'list') return `输入 JSON 数组，如 [{"col": 1}] ${hint}`
  if (t === 'str') return `输入字符串 ${hint}`
  if (t === 'int' || t === 'float') return `输入数值 ${hint}`
  return `输入 JSON 数据 ${hint}`
}

interface OpDebugSession {
  operatorId: number | string
  messages: OpChatMessage[]
  inputValues: Record<string, string>
  paramValues: Record<string, string>
}
const OP_SESSION_KEY = 'datacrab:op_debug_session'

function openDebug(op: any, restore?: Partial<OpDebugSession>) {
  debugOperator.value = op

  for (const key of Object.keys(debugInputValues)) {
    delete debugInputValues[key]
  }
  for (const key of Object.keys(debugParamValues)) {
    delete debugParamValues[key]
  }

  const inputs = (op.inputs || []) as any[]
  for (const input of inputs) {
    debugInputValues[input.name] = restore?.inputValues?.[input.name] ?? ''
  }

  const allParams = (op.parameters || []) as any[]
  const inputNames = new Set(inputs.map((i: any) => i.name))
  for (const param of allParams) {
    if (!inputNames.has(param.name)) {
      if (restore?.paramValues && restore.paramValues[param.name] !== undefined) {
        debugParamValues[param.name] = restore.paramValues[param.name]
      } else {
        debugParamValues[param.name] = param.default !== null && param.default !== undefined
          ? String(param.default)
          : ''
      }
    }
  }

  opMessages.value = restore?.messages ? restore.messages.map(m => ({ ...m, thinkingOpen: false })) : []
  opInput.value = ''
  opStreaming.value = false
  debugDrawer.value = true
  saveOpSession()
}

let opSaveTimer: ReturnType<typeof setTimeout> | null = null
function saveOpSession() {
  if (!debugOperator.value) return
  const data: OpDebugSession = {
    operatorId: debugOperator.value.id,
    messages: opMessages.value,
    inputValues: { ...debugInputValues },
    paramValues: { ...debugParamValues },
  }
  try {
    sessionStorage.setItem(OP_SESSION_KEY, JSON.stringify(data))
  } catch {
    try {
      sessionStorage.setItem(OP_SESSION_KEY, JSON.stringify({ ...data, messages: [] }))
    } catch {
      // 放弃持久化（可能 sessionStorage 已满）
    }
  }
}
function scheduleSaveOpSession() {
  if (opSaveTimer) clearTimeout(opSaveTimer)
  opSaveTimer = setTimeout(saveOpSession, 300)
}
function clearOpSession() {
  sessionStorage.removeItem(OP_SESSION_KEY)
}
async function restoreOpSession() {
  const raw = sessionStorage.getItem(OP_SESSION_KEY)
  if (!raw) return
  try {
    const data = JSON.parse(raw) as Partial<OpDebugSession>
    if (!data.operatorId) return
    const op = await api.get(`/operators/${data.operatorId}`)
    openDebug(op, data)
  } catch {
    clearOpSession()
  }
}

watch(
  [opMessages, () => debugInputValues, () => debugParamValues],
  scheduleSaveOpSession,
  { deep: true }
)

// 息屏防护：页面不可见时阻止对话框关闭
watch(debugDrawer, (newVal, oldVal) => {
  if (oldVal === true && newVal === false && document.hidden) {
    nextTick(() => { debugDrawer.value = true })
  }
})

function handleDebugBeforeClose(done: () => void) {
  if (opStreaming.value || debugRunning.value) {
    ElMessage.warning('正在执行中，请先等待完成或点击停止')
    return
  }
  done()
}

function resetDebug() {
  if (opAbortController) {
    opAbortController.abort()
    opAbortController = null
  }
  opStreaming.value = false
}

async function refreshOpScript() {
  if (!debugOperator.value) return
  saving.value = true
  try {
    const fresh = await api.get(`/operators/${debugOperator.value.id}`)
    debugOperator.value = fresh
    ElMessage.success('算子数据已刷新')
    await loadOperators()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '刷新失败')
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

  const inputs = debugInputs.value
  const optParams = debugOptionalParams.value

  for (const input of inputs) {
    const raw = debugInputValues[input.name] || ''
    pushOpHistory('input-' + input.name, raw)
  }
  for (const param of optParams) {
    const raw = debugParamValues[param.name] || ''
    pushOpHistory('param-' + param.name, raw)
  }

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
    opMessages.value.push({
      role: 'assistant',
      content: res?.success ? '执行完成' : '执行失败',
      runResult: res,
    })
  } catch (e: any) {
    opMessages.value.push({
      role: 'assistant',
      content: '执行失败',
      runResult: {
        success: false,
        error: e.response?.data?.detail || String(e),
      },
    })
  } finally {
    debugRunning.value = false
    nextTick(() => scrollOpToBottom(true))
  }
}

function formatResult(result: any): string {
  try {
    return JSON.stringify(result, null, 2)
  } catch {
    return String(result)
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
const generateThinking = ref('')
const generateContent = ref('')
const generatePhase = ref('')
let generateAbortController: AbortController | null = null

const showModifyDialog = ref(false)
const modifyTarget = ref<any>(null)
const modifyInstruction = ref('')
const modifying = ref(false)
const modifyThinking = ref('')
const modifyContent = ref('')
const modifyPhase = ref('')
let modifyAbortController: AbortController | null = null

function onGenerateDialogClosed() {
  generatePrompt.value = ''
  generateThinking.value = ''
  generateContent.value = ''
  generatePhase.value = ''
}

function onModifyDialogClosed() {
  modifyInstruction.value = ''
  modifyTarget.value = null
  modifyThinking.value = ''
  modifyContent.value = ''
  modifyPhase.value = ''
}

async function handleGenerate() {
  if (!generatePrompt.value.trim()) {
    ElMessage.warning('请输入需求描述')
    return
  }
  generating.value = true
  generateThinking.value = ''
  generateContent.value = ''
  generatePhase.value = ''
  generateAbortController = new AbortController()
  pushGenericHistory(generateHistory, generateHistoryIdx, generatePrompt.value, 'generate')

  try {
    const token = localStorage.getItem('access_token')
    const response = await fetch('/api/v1/operators/generate-stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ prompt: generatePrompt.value.trim() }),
      signal: generateAbortController.signal,
    })

    if (!response.ok) {
      const errText = await response.text()
      throw new Error(errText || `HTTP ${response.status}`)
    }

    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

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
          if (data.type === 'thinking') {
            generateThinking.value += data.content
          } else if (data.type === 'content') {
            generateContent.value += data.content
          } else if (data.type === 'phase') {
            generatePhase.value = data.message
          } else if (data.type === 'done') {
            const op = data.operator
            ElMessage.success(`算子 "${op.display_name || op.name}" 已生成`)
            showGenerateDialog.value = false
            await loadOperators()
            setTimeout(() => openDebug(op), 300)
          } else if (data.type === 'error') {
            ElMessage.error(data.content || '生成失败')
          }
        } catch { /* skip */ }
      }
    }
  } catch (e: any) {
    if (e.name === 'AbortError') {
      ElMessage.info('已取消生成')
    } else {
      ElMessage.error(e.message || '生成失败')
    }
  } finally {
    generating.value = false
    generateAbortController = null
  }
}

function stopGenerate() {
  if (generateAbortController) {
    generateAbortController.abort()
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
  modifyThinking.value = ''
  modifyContent.value = ''
  modifyPhase.value = ''
  modifyAbortController = new AbortController()
  pushGenericHistory(modifyHistory, modifyHistoryIdx, modifyInstruction.value, 'modify')

  try {
    const token = localStorage.getItem('access_token')
    const response = await fetch(`/api/v1/operators/${modifyTarget.value.id}/modify-stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ instruction: modifyInstruction.value.trim() }),
      signal: modifyAbortController.signal,
    })

    if (!response.ok) {
      const errText = await response.text()
      throw new Error(errText || `HTTP ${response.status}`)
    }

    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

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
          if (data.type === 'thinking') {
            modifyThinking.value += data.content
          } else if (data.type === 'content') {
            modifyContent.value += data.content
          } else if (data.type === 'phase') {
            modifyPhase.value = data.message
          } else if (data.type === 'done') {
            const op = data.operator
            ElMessage.success(`算子 "${op.display_name || op.name}" 已修改`)
            showModifyDialog.value = false
            modifyTarget.value = null
            await loadOperators()
            setTimeout(() => openDebug(op), 300)
          } else if (data.type === 'error') {
            ElMessage.error(data.content || '修改失败')
          }
        } catch { /* skip */ }
      }
    }
  } catch (e: any) {
    if (e.name === 'AbortError') {
      ElMessage.info('已取消修改')
    } else {
      ElMessage.error(e.message || '修改失败')
    }
  } finally {
    modifying.value = false
    modifyAbortController = null
  }
}

function stopModify() {
  if (modifyAbortController) {
    modifyAbortController.abort()
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

// ==================== 输入历史记录（localStorage 持久化） ====================
const HISTORY_MAX = 100

function loadOpHistory(key: string): string[] {
  try {
    const raw = localStorage.getItem(`dc_op_history_${key}`)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveOpHistory(key: string, list: string[]) {
  try {
    localStorage.setItem(`dc_op_history_${key}`, JSON.stringify(list.slice(-HISTORY_MAX)))
  } catch {}
}

const inputHistories = reactive<Record<string, string[]>>({})
const inputHistoryIdxs = reactive<Record<string, number>>({})
const inputDrafts = reactive<Record<string, string>>({})

function getOrCreateHistory(fieldKey: string): string[] {
  if (!inputHistories[fieldKey]) {
    inputHistories[fieldKey] = loadOpHistory(fieldKey)
    inputHistoryIdxs[fieldKey] = -1
    inputDrafts[fieldKey] = ''
  }
  return inputHistories[fieldKey]
}

function pushOpHistory(fieldKey: string, value: string) {
  const v = value.trim()
  if (!v) return
  const list = getOrCreateHistory(fieldKey)
  if (list[list.length - 1] !== v) {
    list.push(v)
    if (list.length > HISTORY_MAX) {
      inputHistories[fieldKey] = list.slice(-HISTORY_MAX)
    }
    saveOpHistory(fieldKey, inputHistories[fieldKey])
  }
  inputHistoryIdxs[fieldKey] = -1
}

function onOpHistoryKey(e: KeyboardEvent, fieldKey: string, modelGetter: () => string, modelSetter: (v: string) => void) {
  const list = getOrCreateHistory(fieldKey)
  const idx = inputHistoryIdxs[fieldKey]
  if (e.key === 'ArrowUp') {
    if (list.length === 0) return
    e.preventDefault()
    if (idx === -1) {
      inputDrafts[fieldKey] = modelGetter()
      inputHistoryIdxs[fieldKey] = list.length - 1
    } else if (idx > 0) {
      inputHistoryIdxs[fieldKey] = idx - 1
    }
    modelSetter(list[inputHistoryIdxs[fieldKey]])
  } else if (e.key === 'ArrowDown') {
    if (idx === -1) return
    e.preventDefault()
    if (idx < list.length - 1) {
      inputHistoryIdxs[fieldKey] = idx + 1
      modelSetter(list[inputHistoryIdxs[fieldKey]])
    } else {
      inputHistoryIdxs[fieldKey] = -1
      modelSetter(inputDrafts[fieldKey])
    }
  }
}

function handleInputHistoryKey(e: KeyboardEvent, fieldKey: string, inputName: string) {
  onOpHistoryKey(e, fieldKey, () => debugInputValues[inputName], (v) => { debugInputValues[inputName] = v })
}

function handleParamHistoryKey(e: KeyboardEvent, fieldKey: string, paramName: string) {
  onOpHistoryKey(e, fieldKey, () => debugParamValues[paramName], (v) => { debugParamValues[paramName] = v })
}

const generateHistory = ref<string[]>(loadOpHistory('generate'))
const generateHistoryIdx = ref(-1)
const generateDraft = ref('')

const modifyHistory = ref<string[]>(loadOpHistory('modify'))
const modifyHistoryIdx = ref(-1)
const modifyDraft = ref('')

const opChatHistory = ref<string[]>(loadOpHistory('op_chat'))
const opChatHistoryIdx = ref(-1)
const opChatDraft = ref('')

function onGenerateHistoryKey(e: KeyboardEvent) {
  onHistoryKeyGeneric(e, generateHistory, generateHistoryIdx, generatePrompt, generateDraft)
}

function onModifyHistoryKey(e: KeyboardEvent) {
  onHistoryKeyGeneric(e, modifyHistory, modifyHistoryIdx, modifyInstruction, modifyDraft)
}

function onHistoryKeyGeneric(e: KeyboardEvent, list: Ref<string[]>, idx: Ref<number>, model: Ref<string>, savedDraft: Ref<string>) {
  if (e.key === 'ArrowUp') {
    if (list.value.length === 0) return
    e.preventDefault()
    if (idx.value === -1) {
      savedDraft.value = model.value
      idx.value = list.value.length - 1
    } else if (idx.value > 0) {
      idx.value--
    }
    model.value = list.value[idx.value]
  } else if (e.key === 'ArrowDown') {
    if (idx.value === -1) return
    e.preventDefault()
    if (idx.value < list.value.length - 1) {
      idx.value++
      model.value = list.value[idx.value]
    } else {
      idx.value = -1
      model.value = savedDraft.value
    }
  }
}

function pushGenericHistory(list: Ref<string[]>, idx: Ref<number>, value: string, storageKey: string) {
  const v = value.trim()
  if (!v) return
  if (list.value[list.value.length - 1] !== v) {
    list.value.push(v)
    if (list.value.length > HISTORY_MAX) {
      list.value = list.value.slice(-HISTORY_MAX)
    }
    saveOpHistory(storageKey, list.value)
  }
  idx.value = -1
}

function handleOpKeyDown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleOpSend()
    return
  }
  onHistoryKeyGeneric(e, opChatHistory, opChatHistoryIdx, opInput, opChatDraft)
}

function stopOpGeneration() {
  if (opAbortController) {
    opAbortController.abort()
  }
}

async function handleOpSend() {
  if (!debugOperator.value || !opInput.value.trim() || opStreaming.value) return

  const userMsg = opInput.value.trim()
  opMessages.value.push({ role: 'user', content: userMsg })
  pushGenericHistory(opChatHistory, opChatHistoryIdx, userMsg, 'op_chat')
  opInput.value = ''
  opStreaming.value = true
  opAbortController = new AbortController()

  const assistantIdx = opMessages.value.length
  opMessages.value.push({ role: 'assistant', content: '', thinking: '', thinkingOpen: false })
  opPinnedToBottom.value = true
  await nextTick()
  scrollOpToBottom(true)

  try {
    const token = localStorage.getItem('access_token')
    const history = opMessages.value.slice(0, assistantIdx).map(m => ({
      role: m.role,
      content: m.content + (m.runResult ? `\n\n[执行结果: ${m.runResult.success ? '成功' : '失败'}]` + (m.runResult.error ? ` 错误: ${m.runResult.error}` : '') : '') + (m.scriptUpdated ? `\n\n[代码已更新: ${m.scriptUpdated}]` : ''),
    }))

    const contextData: Record<string, string> = {}
    const inputs = debugInputs.value
    for (const input of inputs) {
      const raw = debugInputValues[input.name] || ''
      if (raw.trim()) contextData[`input_${input.name}`] = raw
    }
    const optParams = debugOptionalParams.value
    for (const param of optParams) {
      const raw = debugParamValues[param.name] || ''
      if (raw.trim()) contextData[`param_${param.name}`] = raw
    }
    const lastRunMsg = [...opMessages.value].reverse().find(m => m.runResult)
    if (lastRunMsg?.runResult) {
      contextData['last_result'] = lastRunMsg.runResult.success ? '成功' : '失败'
      if (lastRunMsg.runResult.error) contextData['last_error'] = lastRunMsg.runResult.error
    }

    const response = await fetch(`/api/v1/operators/${debugOperator.value.id}/debug-chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        message: userMsg,
        history,
        context: contextData,
      }),
      signal: opAbortController.signal,
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
          const msg = opMessages.value[assistantIdx]

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
          } else if (data.type === 'content') {
            if (!thinkingDone && msg.thinking) {
              thinkingDone = true
              msg.thinkingOpen = false
            }
            msg.content += data.content
          } else if (data.type === 'script_updated') {
            msg.scriptUpdated = data.script_name
            try {
              const fresh = await api.get(`/operators/${debugOperator.value.id}`)
              debugOperator.value = fresh
            } catch { /* skip */ }
          } else if (data.type === 'executing') {
            msg.executingMsg = data.message || '正在执行...'
          } else if (data.type === 'run_result') {
            msg.executingMsg = ''
            msg.runResult = data.result
            if (!msg.content) {
              msg.content = data.result?.success ? '执行完成' : '执行失败'
            }
          } else if (data.type === 'error') {
            msg.content += `\n\n错误: ${data.content || '未知错误'}`
          } else if (data.type === 'inspecting') {
            msg.executingMsg = ''
            msg.content += `\n\n🔍 ${data.message || 'DataInspector 正在检查数据质量...'}\n`
            msg.thinking = ''
            msg.thinkingOpen = false
            thinkingDone = false
          } else if (data.type === 'retry') {
            msg.executingMsg = ''
            msg.content += `\n\n---\n🔄 ${data.message || '第' + data.round + '次修复尝试'}\n`
            msg.thinking = ''
            msg.thinkingOpen = false
            thinkingDone = false
          } else if (data.type === 'round') {
            msg.executingMsg = ''
            msg.content += `\n\n═══ 第${data.round}轮修改 ═══\n`
            msg.thinking = ''
            msg.thinkingOpen = false
            thinkingDone = false
          } else if (data.type === 'give_up') {
            msg.content += `\n\n⚠ **多次修复失败，无法自动修复**\n\n${data.reason || ''}`
          }
        } catch {
          // skip
        }
      }
      nextTick(() => scrollOpToBottom())
    }

    const finalMsg = opMessages.value[assistantIdx]
    if (finalMsg.thinking && !thinkingDone) {
      finalMsg.thinking += '\n\n[推理过程已中断]'
    }

  } catch (e: any) {
    if (e.name === 'AbortError') {
      const msg = opMessages.value[assistantIdx]
      if (msg.content) {
        msg.content += '\n\n*[已停止生成]*'
      } else {
        msg.content = '*[已停止生成]*'
      }
    } else {
      opMessages.value[assistantIdx].content = `请求出错: ${e.message || String(e)}`
    }
  } finally {
    opStreaming.value = false
    opAbortController = null
    await nextTick()
    scrollOpToBottom()
  }
}

onMounted(() => {
  loadOperators()
  restoreOpSession()
})
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

.param-section {
  .label {
    font-size: 13px;
    color: #606266;
    margin-bottom: 4px;
    word-break: break-all;
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

  .exec-time {
    font-size: 11px;
    color: #909399;
  }

  .debug-result-error {
    padding: 6px 10px;
    pre {
      margin: 0;
      font-size: 12px;
      color: #f56c6c;
      white-space: pre-wrap;
      word-break: break-all;
    }
  }

  .debug-result-stdout,
  .debug-result-data {
    :deep(.el-collapse-item__header) {
      font-size: 12px;
      height: 28px;
      line-height: 28px;
      padding-left: 10px;
    }
    pre {
      margin: 0;
      font-size: 11px;
      white-space: pre-wrap;
      word-break: break-all;
      max-height: 160px;
      overflow-y: auto;
    }
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

  p {
    font-size: 14px;
    text-align: center;
    line-height: 1.6;
    padding: 0 12px;
  }
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

.debug-msg-avatar {
  flex-shrink: 0;
}

.debug-msg-body {
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
}

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

    .thinking-spin { animation: op-rotate 1.2s linear infinite; }
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

@keyframes op-rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.debug-msg-executing {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 0;
  font-size: 13px;
  color: #909399;

  .thinking-spin {
    animation: op-rotate 1.2s linear infinite;
  }
}

.debug-msg-content {
  font-size: 13px;
  line-height: 1.6;
  overflow-wrap: break-word;
  word-break: break-word;

  :deep(pre) {
    white-space: pre-wrap;
    word-break: break-all;
    overflow-x: auto;
    max-width: 100%;
  }

  :deep(table) {
    width: 100%;
    table-layout: fixed;
    word-break: break-all;
  }

  :deep(code) {
    white-space: pre-wrap;
    word-break: break-all;
  }
}

.debug-msg-script-updated {
  margin-top: 6px;
}

.debug-input-area {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  padding: 12px 16px;
  border-top: 1px solid #ebeef5;
  background: #fff;

  .el-textarea {
    flex: 1;
    font-size: 14px;
  }
  .el-button { margin-bottom: 4px; }
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 6px 0;

  span {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #c0c4cc;
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
</style>

<style lang="scss">
.debug-layout {
  .el-textarea__inner,
  .el-input__inner {
    &::placeholder {
      white-space: pre-wrap;
      word-break: break-all;
    }
  }
}

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

.ai-process-box {
  margin-top: 12px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  overflow: hidden;
}

.ai-phase {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: #ecf5ff;
  font-size: 13px;
  color: #409eff;
  font-weight: 500;
  .phase-spin {
    animation: rotating 1.5s linear infinite;
  }
}

@keyframes rotating {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.ai-thinking {
  border-top: 1px solid #ebeef5;
  .thinking-header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 14px;
    background: #f0f5ff;
    font-size: 12px;
    color: #7c8db5;
    font-weight: 600;
  }
  .thinking-body {
    padding: 10px 14px;
    font-size: 12px;
    color: #606266;
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 200px;
    overflow-y: auto;
    line-height: 1.6;
    background: #fafbfc;
  }
}

.ai-code-preview {
  border-top: 1px solid #ebeef5;
  .code-preview-header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 14px;
    background: #f0f9eb;
    font-size: 12px;
    color: #67c23a;
    font-weight: 600;
  }
  .code-preview-body {
    margin: 0;
    padding: 10px 14px;
    font-size: 12px;
    font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 250px;
    overflow-y: auto;
    line-height: 1.5;
    background: #ffffff;
    border: 1px solid #ebeef5;
    color: #303133;
  }
}
</style>

<style lang="scss">
.markdown-body {
  font-size: 14px;
  line-height: 1.8;
  color: #303133;
  padding: 16px 20px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  max-height: 70vh;
  overflow-y: auto;

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