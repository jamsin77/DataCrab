<template>
  <div class="operator-page">
    <div class="toolbar">
      <div class="toolbar-left">
        <el-button type="success" @click="showGenerateDialog = true">
          <el-icon><MagicStick /></el-icon>
          {{ t('operator.createOperator') }}
        </el-button>
        <el-upload
          :show-file-list="false"
          :before-upload="handleUpload"
          accept=".py"
          :http-request="uploadOperator"
        >
          <el-button type="primary">
            <el-icon><Upload /></el-icon>
            {{ t('operator.importOperator') }}
          </el-button>
        </el-upload>
      </div>
      <div class="toolbar-right">
        <el-select v-model="sortBy" style="width: 120px" @change="loadOperators">
          <el-option :label="t('operator.sortCreatedAt')" value="created" />
          <el-option :label="t('operator.sortUpdatedAt')" value="updated" />
        </el-select>
        <el-input
          v-model="searchQuery"
          :placeholder="t('operator.searchPlaceholder')"
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
            </div>
          </template>
          <p class="op-desc">{{ op.description || t('operator.noDescription') }}</p>
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
                <el-icon><Edit /></el-icon> {{ t('common.edit') }}
              </el-button>
              <el-button size="small" type="success" plain @click="openDebug(op)">
                <el-icon><VideoPlay /></el-icon> {{ t('common.debug') }}
              </el-button>
              <el-button size="small" @click="openCloneDialog(op)">
                <el-icon><CopyDocument /></el-icon> {{ t('common.duplicate') }}
              </el-button>
              <el-button size="small" @click="downloadOperator(op)">
                <el-icon><Download /></el-icon> {{ t('common.download') }}
              </el-button>
              <el-button size="small" type="danger" plain @click="confirmDelete(op)">
                <el-icon><Delete /></el-icon> {{ t('common.delete') }}
              </el-button>
            </div>
          </div>
        </el-card>
    </div>

    <el-empty v-if="filteredOperators.length === 0" :description="t('operator.empty')" />

    <el-dialog
      v-model="debugDrawer"
      :title="t('operator.debugTitle', { name: (debugOperator?.display_name || debugOperator?.name || '') })"
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
            <span>{{ t('operator.operatorParams') }}</span>
            <el-button size="small" text type="primary" @click="refreshOpScript" :loading="saving">
              <el-icon><Refresh /></el-icon> {{ t('operator.refreshScript') }}
            </el-button>
          </div>

          <div class="func-signature">
            <code>{{ debugOperator?.function_name }}({{ signatureParams }})</code>
            <span v-if="debugOperator?.outputs?.length" class="return-type">
              → {{ debugOperator.outputs[0].type }}
            </span>
          </div>

          <div v-if="debugInputs.length" class="param-group">
            <div class="group-title">{{ t('operator.inputs') }}</div>
            <div v-for="input in debugInputs" :key="'in-' + input.name" class="param-section">
              <div class="label">
                {{ input.name }}
                <el-tag size="small" type="primary" effect="plain">{{ input.type }}</el-tag>
                <el-tag size="small" type="danger" effect="plain">{{ t('common.required') }}</el-tag>
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
            <div class="group-title">{{ t('operator.optionalParams') }}</div>
            <div v-for="param in debugOptionalParams" :key="'opt-' + param.name" class="param-section">
              <div class="label">
                {{ param.name }}
                <el-tag size="small" type="warning" effect="plain">{{ param.type }}</el-tag>
                <el-tag size="small" effect="plain" v-if="param.default !== null && param.default !== undefined">
                  {{ t('operator.defaultValue', { value: param.default }) }}
                </el-tag>
              </div>
              <el-input
                v-model="debugParamValues[param.name]"
                :placeholder="String(param.default ?? '')"
              />
            </div>
          </div>

          <div v-if="debugOperator?.outputs?.length" class="param-group">
            <div class="group-title">{{ t('operator.outputs') }}</div>
            <div class="output-info">
              <el-tag type="success" effect="plain">
                {{ debugOperator.outputs[0].name }}: {{ debugOperator.outputs[0].type }}
              </el-tag>
            </div>
          </div>

          <el-button type="primary" @click="runDebug" :loading="debugRunning" style="width: 100%; margin-top: 8px">
            <el-icon><CaretRight /></el-icon> {{ t('operator.runDebug') }}
          </el-button>
        </div>

        <div class="debug-right">
          <div class="debug-chat-header">
            <el-icon><ChatDotRound /></el-icon>
            <span>{{ t('operator.aiCodeAssistant') }}</span>
            <el-button
              size="small"
              plain
              type="danger"
              style="margin-left: auto"
              :disabled="opStreaming || opMessages.length === 0"
              @click="clearOpDebugHistory"
            >
              <el-icon><Delete /></el-icon> {{ t('operator.clearHistory') }}
            </el-button>
          </div>
          <div class="debug-message-list" ref="opMsgListRef" @scroll="onOpListScroll">
            <div v-if="opMessages.length === 0" class="debug-empty">
              <p>{{ t('operator.debugEmptyHint') }}</p>
            </div>
            <div
              v-for="(msg, idx) in opMessages"
              :key="idx"
              class="debug-message"
              :class="msg.role"
            >
              <div class="debug-msg-avatar">
                <el-avatar :size="32" v-if="msg.role === 'assistant'" style="background:#409eff">AI</el-avatar>
                <el-avatar :size="32" v-else style="background:#67c23a">{{ t('common.me') }}</el-avatar>
              </div>
              <div class="debug-msg-body">
                <template v-if="msg.role === 'user'">
                  <div class="debug-msg-user">
                    {{ msg.content }}
                    <el-button text size="small" @click="copyText(msg.content)" class="msg-copy-btn"><el-icon><CopyDocument /></el-icon></el-button>
                  </div>
                  <div class="debug-msg-time" v-if="msg.created_at">{{ formatMsgTime(msg.created_at) }}</div>
                </template>
                <div v-else class="debug-msg-assistant">
                  <div v-if="msg.thinking" class="debug-msg-thinking">
                    <div class="thinking-header" @click="msg.thinkingOpen = !msg.thinkingOpen">
                      <el-icon class="thinking-toggle" :class="{ open: msg.thinkingOpen }"><CaretRight /></el-icon>
                      <span>{{ t('operator.thinking') }}<span v-if="msg.model" class="thinking-model">{{ msg.model }}</span></span>
                      <el-button text size="small" @click.stop="copyText(msg.thinking)" class="msg-copy-btn"><el-icon><CopyDocument /></el-icon></el-button>
                    </div>
                    <div v-show="msg.thinkingOpen" class="thinking-body">{{ msg.thinking }}</div>
                  </div>
                  <el-collapse v-if="msg.content" :model-value="msg._contentOpen === false ? [] : ['content']" @change="(v: any) => { msg._contentOpen = v.length > 0 }">
                    <el-collapse-item name="content">
                      <template #title>
                        <span class="collapse-label">{{ t('operator.aiReply') }}</span>
                        <el-button text size="small" @click.stop="copyText(msg.content)" class="collapse-copy-btn"><el-icon><CopyDocument /></el-icon> {{ t('common.copy') }}</el-button>
                      </template>
                      <div class="debug-msg-content markdown-body" v-html="renderMarkdown(msg.content)"></div>
                    </el-collapse-item>
                  </el-collapse>
                  <div class="debug-msg-time" v-if="msg.created_at">{{ formatMsgTime(msg.created_at) }}</div>
                  <div v-if="msg.executingMsg" class="debug-msg-executing">
                    <el-icon class="thinking-spin"><Loading /></el-icon>
                    <span>{{ msg.executingMsg }}</span>
                  </div>
                  <div v-if="msg.runResult" class="debug-msg-runresult">
                    <div class="runresult-header">
                      <el-tag :type="msg.runResult.success ? 'success' : 'danger'" size="small">
                        {{ msg.runResult.success ? t('operator.runSuccess') : t('operator.runFailed') }}
                      </el-tag>
                      <span v-if="msg.runResult.execution_time_ms" class="exec-time">{{ msg.runResult.execution_time_ms }}ms</span>
                    </div>
                    <div v-if="msg.runResult.error" class="debug-result-error">
                      <el-collapse>
                        <el-collapse-item>
                          <template #title>
                            <span class="collapse-label">{{ t('operator.errorInfo') }}</span>
                            <el-button text size="small" @click.stop="copyText(msg.runResult.error)" class="collapse-copy-btn"><el-icon><CopyDocument /></el-icon> {{ t('common.copy') }}</el-button>
                          </template>
                          <pre>{{ msg.runResult.error }}</pre>
                        </el-collapse-item>
                      </el-collapse>
                    </div>
                    <div v-if="msg.runResult.stdout" class="debug-result-stdout">
                      <el-collapse>
                        <el-collapse-item>
                          <template #title>
                            <span class="collapse-label">{{ t('operator.stdout') }}</span>
                            <el-button text size="small" @click="copyText(msg.runResult.stdout)" class="collapse-copy-btn"><el-icon><CopyDocument /></el-icon> {{ t('common.copy') }}</el-button>
                          </template>
                          <pre>{{ msg.runResult.stdout }}</pre>
                        </el-collapse-item>
                      </el-collapse>
                    </div>
                    <div v-if="msg.runResult.result != null" class="debug-result-data">
                      <el-collapse>
                        <el-collapse-item>
                          <template #title>
                            <span class="collapse-label">{{ t('operator.runResult') }}</span>
                            <el-button text size="small" @click.stop="copyText(formatResult(msg.runResult.result))" class="collapse-copy-btn"><el-icon><CopyDocument /></el-icon> {{ t('common.copy') }}</el-button>
                          </template>
                          <pre>{{ formatResult(msg.runResult.result) }}</pre>
                        </el-collapse-item>
                      </el-collapse>
                    </div>
                  </div>
                  <div v-if="msg.inspectionReport" class="debug-msg-inspection-report">
                    <el-collapse model-value="report">
                      <el-collapse-item name="report">
                        <template #title>
                          <el-icon style="margin-right: 4px;"><CircleCheck /></el-icon>
                          <span class="collapse-label">{{ t('operator.inspectionReport') }}</span>
                          <el-button text size="small" @click.stop="copyText(msg.inspectionReport)" class="collapse-copy-btn"><el-icon><CopyDocument /></el-icon> {{ t('common.copy') }}</el-button>
                        </template>
                        <div class="debug-msg-content markdown-body" v-html="renderMarkdown(msg.inspectionReport)"></div>
                      </el-collapse-item>
                    </el-collapse>
                  </div>
                  <div v-if="msg.scriptUpdated" class="debug-msg-script-updated">
                    <el-tag type="warning" size="small">{{ t('operator.codeUpdated', { name: msg.scriptUpdated }) }}</el-tag>
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
              :placeholder="t('operator.debugInputPlaceholder')"
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

    <el-dialog v-model="showGenerateDialog" :title="t('operator.generateOperator')" width="95%" top="2vh" :close-on-press-escape="false" @closed="onGenerateDialogClosed">
      <el-form label-width="80px">
        <el-form-item :label="t('operator.requirementDesc')">
          <el-input
            v-model="generatePrompt"
            type="textarea"
            :rows="4"
            :placeholder="t('operator.generatePlaceholder')"
            @keydown="onGenerateHistoryKey"
          />
        </el-form-item>
      </el-form>
      <div v-if="genMessages.length" class="gen-msg-list">
        <div v-for="(msg, idx) in genMessages" :key="idx" class="debug-message" :class="msg.role">
          <div class="debug-msg-avatar">
            <el-avatar :size="32" v-if="msg.role === 'assistant'" style="background:#409eff">AI</el-avatar>
            <el-avatar :size="32" v-else style="background:#67c23a">{{ t('common.me') }}</el-avatar>
          </div>
          <div class="debug-msg-body">
            <template v-if="msg.role === 'user'">
              <div class="debug-msg-user">{{ msg.content }}</div>
              <div class="debug-msg-time" v-if="msg.created_at">{{ formatMsgTime(msg.created_at) }}</div>
            </template>
            <div v-else class="debug-msg-assistant">
              <div v-if="msg.thinking" class="debug-msg-thinking">
                <div class="thinking-header" @click="msg.thinkingOpen = !msg.thinkingOpen">
                  <el-icon class="thinking-toggle" :class="{ open: msg.thinkingOpen }"><CaretRight /></el-icon>
                  <span>{{ t('operator.thinking') }}</span>
                </div>
                <div v-show="msg.thinkingOpen" class="thinking-body">{{ msg.thinking }}</div>
              </div>
              <div v-if="msg.content" class="debug-msg-content markdown-body" v-html="renderMarkdown(msg.content)"></div>
              <div v-if="generating && idx === genMessages.length - 1 && !msg.content && !msg.thinking" class="typing-indicator"><span></span><span></span><span></span></div>
            </div>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="showGenerateDialog = false" :disabled="generating">{{ t('common.cancel') }}</el-button>
        <el-button
          v-if="generating"
          type="danger"
          @click="stopGenerate"
        >
          <el-icon><VideoPause /></el-icon> {{ t('common.stop') }}
        </el-button>
        <el-button type="primary" @click="handleGenerate" :loading="generating || checkingSimilar" :disabled="generating || checkingSimilar">
          {{ generating ? t('operator.generating') : (checkingSimilar ? t('operator.checkingSimilar') : t('operator.startGenerate')) }}
        </el-button>
      </template>
    </el-dialog>

    <!-- ==================== Similar Operator Detection Dialog ==================== -->
    <el-dialog v-model="showSimilarDialog" :title="t('operator.similarFound')" width="600px" :close-on-click-modal="false">
      <el-alert type="warning" :closable="false" style="margin-bottom: 16px">
        <template #title>{{ t('operator.similarHint') }}</template>
      </el-alert>

      <div v-for="op in similarOperators" :key="op.id" class="similar-op-item">
        <div class="similar-op-header">
          <span class="similar-op-name">{{ op.display_name || op.name }}</span>
          <span class="similar-op-score">{{ t('operator.similarity') }} {{ (op.similarity * 100).toFixed(0) }}%</span>
        </div>
        <div class="similar-op-desc">{{ op.description || t('operator.noDescriptionParen') }}</div>

        <div v-if="op.can_use" class="similar-op-actions">
          <el-button type="primary" size="small" @click="openExistingOperator(op)">{{ t('operator.viewOperator') }}</el-button>
        </div>
        <div v-else class="similar-op-contact">
          <el-alert type="info" :closable="false">
            <template #title>
              {{ t('operator.noPermission', { owner: op.owner_name, email: op.owner_email }) }}
            </template>
          </el-alert>
        </div>
      </div>

      <template #footer>
        <el-button @click="showSimilarDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="proceedToGenerate">{{ t('operator.stillCreate') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showModifyDialog" :title="t('operator.modifyOperator')" width="95%" top="2vh" :close-on-press-escape="false" @closed="onModifyDialogClosed">
      <div v-if="modifyTarget" class="modify-target-info">
        <el-tag>{{ modifyTarget.display_name || modifyTarget.name }}</el-tag>
        <span class="modify-desc">{{ modifyTarget.description || t('operator.noDescription') }}</span>
      </div>
      <el-form label-width="80px" style="margin-top: 12px">
        <el-form-item :label="t('operator.modifyInstruction')">
          <el-input
            v-model="modifyInstruction"
            type="textarea"
            :rows="4"
            :placeholder="t('operator.modifyPlaceholder')"
            @keydown="onModifyHistoryKey"
          />
        </el-form-item>
      </el-form>
      <div v-if="modifyMessages.length" class="gen-msg-list">
        <div v-for="(msg, idx) in modifyMessages" :key="idx" class="debug-message" :class="msg.role">
          <div class="debug-msg-avatar">
            <el-avatar :size="32" v-if="msg.role === 'assistant'" style="background:#409eff">AI</el-avatar>
            <el-avatar :size="32" v-else style="background:#67c23a">{{ t('common.me') }}</el-avatar>
          </div>
          <div class="debug-msg-body">
            <template v-if="msg.role === 'user'">
              <div class="debug-msg-user">{{ msg.content }}</div>
              <div class="debug-msg-time" v-if="msg.created_at">{{ formatMsgTime(msg.created_at) }}</div>
            </template>
            <div v-else class="debug-msg-assistant">
              <div v-if="msg.thinking" class="debug-msg-thinking">
                <div class="thinking-header" @click="msg.thinkingOpen = !msg.thinkingOpen">
                  <el-icon class="thinking-toggle" :class="{ open: msg.thinkingOpen }"><CaretRight /></el-icon>
                  <span>{{ t('operator.thinking') }}</span>
                </div>
                <div v-show="msg.thinkingOpen" class="thinking-body">{{ msg.thinking }}</div>
              </div>
              <div v-if="msg.content" class="debug-msg-content markdown-body" v-html="renderMarkdown(msg.content)"></div>
              <div v-if="modifying && idx === modifyMessages.length - 1 && !msg.content && !msg.thinking" class="typing-indicator"><span></span><span></span><span></span></div>
            </div>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="showModifyDialog = false" :disabled="modifying">{{ t('common.cancel') }}</el-button>
        <el-button
          v-if="modifying"
          type="danger"
          @click="stopModify"
        >
          <el-icon><VideoPause /></el-icon> {{ t('common.stop') }}
        </el-button>
        <el-button type="primary" @click="handleModify" :loading="modifying" :disabled="modifying">
          {{ modifying ? t('operator.modifying') : t('operator.startModify') }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showCloneDialog" :title="t('operator.cloneTitle')" width="450px" @closed="cloneName = ''; cloneTarget = null">
      <div v-if="cloneTarget" class="modify-target-info">
        <el-tag>{{ cloneTarget.display_name || cloneTarget.name }}</el-tag>
        <span class="modify-desc">{{ t('operator.cloneHint') }}</span>
      </div>
      <el-form label-width="80px" style="margin-top: 12px">
        <el-form-item :label="t('operator.newName')" required>
          <el-input
            v-model="cloneName"
            :placeholder="t('operator.newNamePlaceholder')"
            @keyup.enter="handleClone"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCloneDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="handleClone" :loading="cloning" :disabled="!cloneName.trim()">
          {{ cloning ? t('operator.cloning') : t('operator.confirmClone') }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, nextTick, watch, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Upload, Download, Delete, VideoPlay, CaretRight, Search, Check, MagicStick, Edit, CopyDocument, VideoPause, Loading, Document, Cpu, ChatDotRound, Promotion, Refresh, CircleCheck } from '@element-plus/icons-vue'
import api from '@/api/index'
import { ElMessage, ElMessageBox } from 'element-plus'
import markdownIt from 'markdown-it'
import { formatTime } from '@/utils/time'

const { t } = useI18n()

const md = markdownIt({ html: false, breaks: true, linkify: true })
function renderMarkdown(text: string) {
  return md.render(text || '')
}
function formatMsgTime(ts?: string): string {
  return formatTime(ts)
}

function copyText(text: string) {
  navigator.clipboard.writeText(text).then(() => ElMessage.success(t('common.copied'))).catch(() => ElMessage.error(t('common.copyFailed')))
}

const operators = ref<any[]>([])
const searchQuery = ref('')
const sortBy = ref('created')

const filteredOperators = computed(() => {
  let list = operators.value
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
    operators.value = await api.get(`/operators?sort_by=${sortBy.value}`)
  } catch (e: any) {
    ElMessage.error(t('operator.loadFailed'))
  }
}

async function uploadOperator(options: any) {
  const formData = new FormData()
  formData.append('file', options.file)
  try {
    const res = await api.post('/operators/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    ElMessage.success(t('operator.uploadSuccess', { name: (res.display_name || res.name) }))
    await loadOperators()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || t('operator.uploadFailed'))
  }
}

function handleUpload(file: any) {
  const isPython = file.name.toLowerCase().endsWith('.py')
  if (!isPython) {
    ElMessage.error(t('operator.pyOnly'))
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
      t('operator.deleteOperatorConfirm', { name: (op.display_name || op.name) }),
      t('operator.confirmDeleteTitle'),
      { confirmButtonText: t('common.delete'), cancelButtonText: t('common.cancel'), type: 'warning' }
    )
    await api.delete(`/operators/${op.id}`)
    ElMessage.success(t('operator.deleteSuccess'))
    await loadOperators()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e.response?.data?.detail || t('operator.deleteFailed'))
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
  created_at?: string
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
  const hint = t('operator.historyHint')
  const inputType = input.type || 'any'
  if (inputType === 'DataFrame' || inputType === 'list') return `${t('operator.inputPlaceholderJson')} ${hint}`
  if (inputType === 'str') return `${t('operator.inputPlaceholderStr')} ${hint}`
  if (inputType === 'int' || inputType === 'float') return `${t('operator.inputPlaceholderNum')} ${hint}`
  return `${t('operator.inputPlaceholderDefault')} ${hint}`
}

interface OpDebugSession {
  operatorId: number | string
  messages: OpChatMessage[]
  inputValues: Record<string, string>
  paramValues: Record<string, string>
}
const OP_LAST_KEY = 'datacrab:op_debug:last'
const DEBUG_MSG_MAX = 50

function opDebugKey(opId: number | string): string {
  return `datacrab:op_debug:${opId}`
}

function loadOpDebugSession(opId: number | string): Partial<OpDebugSession> | null {
  try {
    const raw = localStorage.getItem(opDebugKey(opId))
    if (!raw) return null
    const data = JSON.parse(raw)
    if (data.messages) data.messages = data.messages.map((m: any) => ({ ...m, thinkingOpen: false, executingMsg: undefined }))
    return data
  } catch { return null }
}

function saveOpDebugSession(opId: number | string, data: OpDebugSession) {
  try {
    const stripped = {
      ...data,
      messages: data.messages.slice(-DEBUG_MSG_MAX).map(m => ({ ...m, executingMsg: undefined, thinkingOpen: false })),
    }
    localStorage.setItem(opDebugKey(opId), JSON.stringify(stripped))
    localStorage.setItem(OP_LAST_KEY, String(opId))
  } catch {
    try {
      const lite = {
        ...data,
        messages: data.messages.slice(-DEBUG_MSG_MAX).map(m => ({ role: m.role, content: m.content, scriptUpdated: m.scriptUpdated, model: m.model, created_at: m.created_at })),
      }
      localStorage.setItem(opDebugKey(opId), JSON.stringify(lite))
      localStorage.setItem(OP_LAST_KEY, String(opId))
    } catch { /* quota exceeded */ }
  }
}

function openDebug(op: any, restore?: Partial<OpDebugSession>) {
  // Load operator history from localStorage when no restore is provided
  if (!restore) {
    restore = loadOpDebugSession(op.id) || undefined
  }
  debugOperator.value = op
  reloadOpHistories(op.id)

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
  saveOpDebugSession(debugOperator.value.id, data)
}
function scheduleSaveOpSession() {
  if (opSaveTimer) clearTimeout(opSaveTimer)
  opSaveTimer = setTimeout(saveOpSession, 500)
}
function clearOpSession() {
  if (debugOperator.value) {
    localStorage.removeItem(opDebugKey(debugOperator.value.id))
  }
  localStorage.removeItem(OP_LAST_KEY)
}
async function restoreOpSession() {
  const lastId = localStorage.getItem(OP_LAST_KEY)
  if (!lastId) return
  try {
    const data = loadOpDebugSession(lastId)
    if (!data) return
    const op = await api.get(`/operators/${lastId}`)
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

// Screen-off protection: prevent dialog close when page is not visible
watch(debugDrawer, (newVal, oldVal) => {
  if (oldVal === true && newVal === false && document.hidden) {
    nextTick(() => { debugDrawer.value = true })
  }
})

function handleDebugBeforeClose(done: () => void) {
  if (opStreaming.value || debugRunning.value) {
    ElMessage.warning(t('operator.executingWarn'))
    return
  }
  done()
}

async function clearOpDebugHistory() {
  try {
    await ElMessageBox.confirm(t('operator.clearDebugConfirm'), t('common.info'), { type: 'warning' })
  } catch { return }
  if (debugOperator.value) {
    localStorage.removeItem(opDebugKey(debugOperator.value.id))
  }
  opMessages.value = []
  ElMessage.success(t('operator.clearDebugSuccess'))
}

function resetDebug() {
  if (opAbortController) {
    opAbortController.abort()
    opAbortController = null
  }
  opStreaming.value = false
  // Clean up incomplete assistant message after abort (no result, no script update)
  const lastMsg = opMessages.value[opMessages.value.length - 1]
  if (lastMsg && lastMsg.role === 'assistant' && !lastMsg.runResult && !lastMsg.scriptUpdated) {
    const trimmed = (lastMsg.llmContent || lastMsg.content || '').replace(/\[已停止生成\]/g, '').trim()
    if (!trimmed) {
      opMessages.value.pop()
    }
  }
}

async function refreshOpScript() {
  if (!debugOperator.value) return
  saving.value = true
  try {
    const fresh = await api.get(`/operators/${debugOperator.value.id}`)
    debugOperator.value = fresh
    ElMessage.success(t('operator.refreshSuccess'))
    await loadOperators()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || t('operator.refreshFailed'))
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
  const _userText = opInput.value.trim()
  opMessages.value.push({ role: 'user', content: _userText ? `${_userText}\n${t('operator.runSkillHint')}` : t('operator.runSkillHint'), created_at: new Date().toISOString() })
  opInput.value = ''
  nextTick(() => scrollOpToBottom(true))

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
      content: res?.success ? t('operator.executionComplete') : t('operator.runFailed'),
      runResult: res,
    })
  } catch (e: any) {
    opMessages.value.push({
      role: 'assistant',
      content: t('operator.runFailed'),
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

const showGenerateDialog = ref(false)
const generatePrompt = ref('')
const generating = ref(false)
const genMessages = ref<any[]>([])
let generateAbortController: AbortController | null = null

const showSimilarDialog = ref(false)
const similarOperators = ref<any[]>([])
const checkingSimilar = ref(false)

const showModifyDialog = ref(false)
const modifyTarget = ref<any>(null)
const modifyInstruction = ref('')
const modifying = ref(false)
const modifyMessages = ref<any[]>([])
let modifyAbortController: AbortController | null = null

function onGenerateDialogClosed() {
  generatePrompt.value = ''
  genMessages.value = []
}

function onModifyDialogClosed() {
  modifyInstruction.value = ''
  modifyTarget.value = null
  modifyMessages.value = []
}

async function handleGenerate() {
  if (!generatePrompt.value.trim()) {
    ElMessage.warning(t('operator.requirementRequired'))
    return
  }
  const userText = generatePrompt.value.trim()
  checkingSimilar.value = true
  try {
    const resp = await api.post('/operators/check-similar', { prompt: userText })
    if (resp.has_similar && resp.operators.length > 0) {
      similarOperators.value = resp.operators
      showSimilarDialog.value = true
      return
    }
  } catch {
    // Similarity check failure does not block; continue generation
  } finally {
    checkingSimilar.value = false
  }
  await doGenerate(userText)
}

async function doGenerate(userText: string) {
  generating.value = true
  genMessages.value = []
  genMessages.value.push({ role: 'user', content: userText, created_at: new Date().toISOString() })
  genMessages.value.push({ role: 'assistant', content: '', thinking: '', thinkingOpen: false, created_at: new Date().toISOString() })
  generateAbortController = new AbortController()
  pushGenericHistory(generateHistory, generateHistoryIdx, userText, 'generate')

  try {
    const token = localStorage.getItem('access_token')
    const response = await fetch('/api/v1/operators/generate-stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ prompt: userText }),
      signal: generateAbortController.signal,
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
          const msg = genMessages.value[genMessages.value.length - 1]
          if (data.type === 'clear_thinking') {
            msg.thinking = ''; msg.content = ''; msg.thinkingOpen = false; thinkingDone = false
          } else if (data.type === 'thinking') {
            if (thinkingDone && msg.thinking) { msg.thinking += `\n\n${t('operator.newRoundReasoning')}\n`; msg.thinkingOpen = false; thinkingDone = false }
            if (!msg.thinking) msg.thinkingOpen = false
            msg.thinking = (msg.thinking || '') + data.content
          } else if (data.type === 'content') {
            if (!thinkingDone && msg.thinking) { thinkingDone = true; msg.thinkingOpen = false }
            msg.content += data.content
          } else if (data.type === 'phase') {
            if (!thinkingDone && msg.thinking) { thinkingDone = true; msg.thinkingOpen = false }
            msg.content += (msg.content ? '\n' : '') + `**[${data.message}]**`
          } else if (data.type === 'done') {
            const op = data.operator
            msg.content += (msg.content ? '\n\n' : '') + `✅ ${t('operator.generateSuccessMsg', { name: (op.display_name || op.name) })}`
            ElMessage.success(t('operator.generateSuccessMsg', { name: (op.display_name || op.name) }))
            showGenerateDialog.value = false
            await loadOperators()
            setTimeout(() => openDebug(op), 300)
          } else if (data.type === 'error') {
            msg.content += (msg.content ? '\n\n' : '') + `❌ ${data.content || t('operator.generateFailedMsg')}`
            ElMessage.error(data.content || t('operator.generateFailedMsg'))
          }
        } catch { /* skip */ }
      }
    }
  } catch (e: any) {
    const msg = genMessages.value[genMessages.value.length - 1]
    if (msg) {
      if (e.name === 'AbortError') {
        msg.content += `\n\n${t('operator.generateCancelled')}`
      } else {
        msg.content += `\n\n❌ ${e.message || t('operator.generateFailedMsg')}`
      }
    }
  } finally {
    generating.value = false
    generateAbortController = null
  }
}

async function openExistingOperator(op: any) {
  showSimilarDialog.value = false
  showGenerateDialog.value = false
  await loadOperators()
  const found = operators.value.find((o: any) => o.id === op.id)
  if (found) {
    openDebug(found)
  }
}

async function proceedToGenerate() {
  showSimilarDialog.value = false
  await doGenerate(generatePrompt.value.trim())
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
    ElMessage.warning(t('operator.modifyRequired'))
    return
  }
  if (!modifyTarget.value) return
  modifying.value = true
  const userText = modifyInstruction.value.trim()
  modifyMessages.value.push({ role: 'user', content: userText, created_at: new Date().toISOString() })
  modifyMessages.value.push({ role: 'assistant', content: '', thinking: '', thinkingOpen: false, model: '', created_at: new Date().toISOString() })
  modifyAbortController = new AbortController()
  pushGenericHistory(modifyHistory, modifyHistoryIdx, userText, 'modify')

  try {
    const token = localStorage.getItem('access_token')
    const response = await fetch(`/api/v1/operators/${modifyTarget.value.id}/modify-stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ instruction: userText }),
      signal: modifyAbortController.signal,
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
          const msg = modifyMessages.value[modifyMessages.value.length - 1]
          if (data.type === 'model') {
            msg.model = data.content
          } else if (data.type === 'clear_thinking') {
            msg.thinking = ''; msg.content = ''; msg.thinkingOpen = false; thinkingDone = false
          } else if (data.type === 'thinking') {
            if (thinkingDone && msg.thinking) { msg.thinking += `\n\n${t('operator.newRoundReasoning')}\n`; msg.thinkingOpen = false; thinkingDone = false }
            if (!msg.thinking) msg.thinkingOpen = false
            msg.thinking = (msg.thinking || '') + data.content
          } else if (data.type === 'content') {
            if (!thinkingDone && msg.thinking) { thinkingDone = true; msg.thinkingOpen = false }
            msg.content += data.content
          } else if (data.type === 'phase') {
            if (!thinkingDone && msg.thinking) { thinkingDone = true; msg.thinkingOpen = false }
            msg.content += (msg.content ? '\n' : '') + `**[${data.message}]**`
          } else if (data.type === 'done') {
            const op = data.operator
            msg.content += (msg.content ? '\n\n' : '') + `✅ ${t('operator.modifySuccessMsg', { name: (op.display_name || op.name) })}`
            ElMessage.success(t('operator.modifySuccessMsg', { name: (op.display_name || op.name) }))
            showModifyDialog.value = false
            modifyTarget.value = null
            await loadOperators()
            setTimeout(() => openDebug(op), 300)
          } else if (data.type === 'error') {
            msg.content += (msg.content ? '\n\n' : '') + `❌ ${data.content || t('operator.modifyFailedMsg')}`
            ElMessage.error(data.content || t('operator.modifyFailedMsg'))
          }
        } catch { /* skip */ }
      }
    }
  } catch (e: any) {
    const msg = modifyMessages.value[modifyMessages.value.length - 1]
    if (msg) {
      if (e.name === 'AbortError') {
        msg.content += `\n\n${t('operator.modifyCancelled')}`
      } else {
        msg.content += `\n\n❌ ${e.message || t('operator.modifyFailedMsg')}`
      }
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
  cloneName.value = (op.display_name || op.name) + t('operator.copySuffix')
  showCloneDialog.value = true
}

async function handleClone() {
  if (!cloneName.value.trim()) {
    ElMessage.warning(t('operator.newNameRequired'))
    return
  }
  if (!cloneTarget.value) return
  cloning.value = true
  try {
    const res = await api.post(`/operators/${cloneTarget.value.id}/clone`, {
      name: cloneName.value.trim(),
    })
    ElMessage.success(t('operator.cloneSuccess', { name: (res.display_name || res.name) }))
    showCloneDialog.value = false
    cloneName.value = ''
    cloneTarget.value = null
    await loadOperators()
    setTimeout(() => openDebug(res), 300)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || t('operator.cloneFailed'))
  } finally {
    cloning.value = false
  }
}

// ==================== Input History (localStorage persistence) ====================
const HISTORY_MAX = 100

function loadOpHistory(key: string): string[] {
  if (!_curOpId) return []
  const newKey = `dc_op_history_${_curOpId}_${key}`
  const oldKey = `dc_op_history_${key}`
  try {
    const raw = localStorage.getItem(newKey)
    if (raw) return JSON.parse(raw)
    const legacy = localStorage.getItem(oldKey)
    if (legacy) {
      const parsed = JSON.parse(legacy)
      localStorage.setItem(newKey, JSON.stringify(parsed))
      localStorage.removeItem(oldKey)
      return parsed
    }
    return []
  } catch {
    return []
  }
}

function saveOpHistory(key: string, list: string[]) {
  if (!_curOpId) return
  try {
    localStorage.setItem(`dc_op_history_${_curOpId}_${key}`, JSON.stringify(list.slice(-HISTORY_MAX)))
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

const generateHistory = ref<string[]>([])
const generateHistoryIdx = ref(-1)
const generateDraft = ref('')

const modifyHistory = ref<string[]>([])
const modifyHistoryIdx = ref(-1)
const modifyDraft = ref('')

const opChatHistory = ref<string[]>([])
const opChatHistoryIdx = ref(-1)
const opChatDraft = ref('')

let _curOpId = ''
function reloadOpHistories(opId: number | string) {
  _curOpId = String(opId)
  for (const key of Object.keys(inputHistories)) {
    delete inputHistories[key]
    delete inputHistoryIdxs[key]
    delete inputDrafts[key]
  }
  generateHistory.value = loadOpHistory('generate')
  modifyHistory.value = loadOpHistory('modify')
  opChatHistory.value = loadOpHistory('op_chat')
  generateHistoryIdx.value = -1
  modifyHistoryIdx.value = -1
  opChatHistoryIdx.value = -1
}

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
  opMessages.value.push({ role: 'user', content: userMsg, created_at: new Date().toISOString() })
  pushGenericHistory(opChatHistory, opChatHistoryIdx, userMsg, 'op_chat')
  opInput.value = ''
  opStreaming.value = true
  opAbortController = new AbortController()

  const assistantIdx = opMessages.value.length
  opMessages.value.push({ role: 'assistant', content: '', llmContent: '', thinking: '', thinkingOpen: false, created_at: new Date().toISOString() })
  opPinnedToBottom.value = true
  await nextTick()
  scrollOpToBottom(true)

  try {
    const token = localStorage.getItem('access_token')
    const history = opMessages.value.slice(0, assistantIdx - 1).map(m => ({
      role: m.role,
      content: (m.llmContent != null ? m.llmContent : m.content) + (m.runResult ? `\n\n${t('operator.execResultHistory', { result: m.runResult.success ? t('common.success') : t('common.failed') })}` + (m.runResult.error ? t('operator.errorHistory', { error: m.runResult.error }) : '') : '') + (m.scriptUpdated ? `\n\n${t('operator.codeUpdatedHistory', { name: m.scriptUpdated })}` : ''),
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
      contextData['last_result'] = lastRunMsg.runResult.success ? t('common.success') : t('common.failed')
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
          } else if (data.type === 'ping') {
            // SSE heartbeat, ignore
          } else if (data.type === 'clear_thinking') {
            msg.thinking = ''
            msg.content = ''
            msg.llmContent = ''
            msg.thinkingOpen = false
            thinkingDone = false
          } else if (data.type === 'thinking') {
            if (thinkingDone && msg.thinking) {
              msg.thinking += `\n\n${t('operator.newRoundReasoning')}\n`
              msg.thinkingOpen = false
              thinkingDone = false
            }
            if (!msg.thinking) msg.thinkingOpen = false
            msg.thinking = (msg.thinking || '') + data.content
          } else if (data.type === 'content') {
            if (!thinkingDone && msg.thinking) {
              thinkingDone = true
              msg.thinkingOpen = false
            }
            msg.content += data.content
            msg.llmContent = (msg.llmContent || '') + data.content
          } else if (data.type === 'tool_action') {
            msg.toolActions = msg.toolActions || []
            for (const act of (data.actions || [])) {
              const icon = act.icon || ''
              const script = act.script || 'main.py'
              const detail = act.detail || ''
              let line = `${icon} ${script}${detail ? ' ' + detail : ''}`
              if (act.diff) line += '\n```diff\n' + act.diff + '\n```'
              msg.content += (msg.content ? '\n' : '') + line
              msg.toolActions.push(act)
            }
          } else if (data.type === 'tool_summary') {
            for (const s of (data.summaries || [])) {
              msg.content += (msg.content ? '\n' : '') + s
            }
          } else if (data.type === 'script_updated') {
            msg.scriptUpdated = data.script_name
            try {
              const fresh = await api.get(`/operators/${debugOperator.value.id}`)
              debugOperator.value = fresh
            } catch { /* skip */ }
          } else if (data.type === 'progress') {
            msg.executingMsg = data.message || ''
          } else if (data.type === 'executing') {
            msg.executingMsg = data.message || t('operator.executingMsg')
          } else if (data.type === 'run_result') {
            msg.executingMsg = ''
            const r = data.result || {}
            const inner = typeof r.result === 'object' && r.result ? r.result : {}
            const failed = !r.success || inner.success === false || (r.error && String(r.error).trim()) || (inner.error && String(inner.error).trim())
            msg.runResult = { ...r, success: !failed, error: r.error || inner.error || '' }
            if (failed) {
              const errMsg = String(r.error || inner.error || t('operator.unknownError')).substring(0, 300)
              msg.content += `\n❌ ${t('operator.execFailedPrefix', { error: errMsg })}\n`
            } else if (!msg.content) {
              msg.content = t('operator.executionComplete')
            }
          } else if (data.type === 'error') {
            msg.content += `\n\n${t('operator.errorHistory', { error: (data.content || t('operator.unknownError')) }).trimStart()}`
          } else if (data.type === 'inspection_report') {
            msg.inspectionReport = data.report
          } else if (data.type === 'inspecting') {
            msg.executingMsg = ''
            msg.content += `\n\n🔍 ${data.message || t('operator.inspectingData')}\n`
            msg.thinkingOpen = false
            thinkingDone = true
          } else if (data.type === 'retry') {
            msg.executingMsg = ''
            msg.content += `\n\n---\n🔄 ${data.message || t('operator.startFix')}\n`
            msg.thinkingOpen = false
            thinkingDone = true
          } else if (data.type === 'round') {
            msg.executingMsg = ''
            msg.thinkingOpen = false
            thinkingDone = true
            msg.content += `\n\n─── ${t('operator.roundLabel', { n: data.round, action: data.action === 'execute' ? t('operator.executeAction') : t('operator.modifyAction') })} ───\n`
          } else if (data.type === 'give_up') {
            msg.content += `\n\n⚠ **${t('operator.fixFailedTitle')}**${data.reason ? '\n' + data.reason : t('operator.cannotAutoFix')}`
          } else if (data.type === 'fatal') {
            const issues = data.issues || []
            let fatalText = `\n\n🚫 **${t('operator.fatalIssue')}**\n\n${data.summary || ''}\n`
            for (const issue of issues) {
              fatalText += `\n- [FATAL] ${issue.description || ''}`
              if (issue.suggestion) fatalText += `\n  → ${issue.suggestion}`
            }
            msg.content += fatalText
          } else if (data.type === 'warning_confirmation') {
            const issues = data.issues || []
            let warnText = `\n\n⚠ **${t('operator.warningIssues')}**\n\n${data.summary || ''}\n`
            for (const issue of issues) {
              warnText += `\n- [WARNING] ${issue.description || ''}`
              if (issue.column) warnText += t('common.columnLabel', { column: issue.column })
              if (issue.suggestion) warnText += `\n  → ${issue.suggestion}`
            }
            warnText += `\n\n> ${t('operator.fixWarningReply')}`
            msg.content += warnText
          } else if (data.type === 'platform_issue') {
            msg.executingMsg = ''
            msg.content += `\n\n🔧 **${t('operator.platformIssueDesc')}**\n\n${data.reason || data.message || ''}\n`
            msg.thinkingOpen = false
            thinkingDone = true
          } else if (data.type === 'done') {
            msg.executingMsg = ''
            if (!msg.content || msg.content.trim() === '') {
              msg.content = t('operator.debugComplete')
            } else if (!msg.content.includes('✅') && !msg.content.includes('⚠') && !msg.content.includes('🔧') && !msg.content.includes('🚫')) {
              msg.content += `\n\n${t('operator.debugComplete')}`
            }
            msg.thinkingOpen = false
          }
        } catch {
          // skip
        }
      }
      nextTick(() => scrollOpToBottom())
    }

    const finalMsg = opMessages.value[assistantIdx]
    if (finalMsg.thinking && !thinkingDone) {
      finalMsg.thinking += `\n\n${t('operator.thinkingInterrupted')}`
    }

  } catch (e: any) {
    if (e.name === 'AbortError') {
      const msg = opMessages.value[assistantIdx]
      if (msg.content) {
        msg.content += `\n\n${t('operator.stoppedGenerate')}`
      } else {
        msg.content = t('operator.stoppedGenerate')
      }
    } else {
      opMessages.value[assistantIdx].content = t('operator.requestError', { msg: (e.message === 'network error' || e.message === 'Failed to fetch' ? t('operator.connectionError') : e.message || String(e)) })
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
  flex-wrap: wrap;
  
  .toolbar-left {
    display: flex;
    gap: 12px;
    align-items: center;
    flex-wrap: wrap;
  }
  
  .toolbar-right {
    display: flex;
    gap: 12px;
    align-items: center;
    flex-wrap: wrap;
  }
}

.op-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
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
  }
  .op-actions {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-top: auto;
    padding-top: 12px;

    .op-actions-row {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 4px;
      align-items: center;

      .el-button {
        margin-left: 0;
        padding: 5px 8px;
        font-size: 12px;
      }
    }
  }
}

.debug-layout {
  display: flex;
  gap: 16px;
  height: calc(92vh - 60px);
}

.gen-msg-list {
  max-height: calc(92vh - 280px);
  overflow-y: auto;
  padding: 4px 0;
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

  :deep(.el-collapse) {
    border-top: none;
    border-bottom: none;
  }

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

  /* 所有 debug 折叠区域统一样式 */
  .debug-msg-assistant :deep(.el-collapse-item__header) {
    position: relative;
    height: 32px;
    line-height: 32px;
    padding: 0 10px;
    font-size: 12px;
    background: #f5f7fa;
    border-bottom: 1px solid #e4e7ed;
  }
  .collapse-label {
    color: #909399;
    font-size: 12px;
  }
  .collapse-copy-btn {
    position: absolute;
    right: 32px;
    top: 50%;
    transform: translateY(-50%);
    padding: 2px 6px;
    font-size: 12px;
    z-index: 1;
  }
  .msg-copy-btn {
    padding: 2px 4px;
    font-size: 12px;
    color: #909399;
    &:hover { color: #409eff; }
  }
  .debug-msg-user .msg-copy-btn { margin-left: 8px; vertical-align: middle; }
  .thinking-header .msg-copy-btn { margin-left: auto; }
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
    .debug-msg-time {
      font-size: 11px;
      color: #999;
      margin-top: 2px;
    }
  }

  &.assistant {
    align-self: stretch;
    max-width: 100%;

    .debug-msg-assistant {
      background: #fff;
      border: 1px solid #e4e7ed;
      border-radius: 10px 10px 10px 2px;
      padding: 8px 12px;
      width: 100%;
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
  flex: 1;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
}

.debug-message.user .debug-msg-body {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
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
    position: sticky;
    top: 0;
    z-index: 10;
    background: #f5f7fa;
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

.debug-msg-inspection-report {
  margin-top: 6px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  overflow: hidden;

  :deep(.el-collapse) {
    border-top: none;
    border-bottom: none;
  }
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

.similar-op-item {
  padding: 12px 0;
  border-bottom: 1px solid #f0f0f0;
  &:last-child { border-bottom: none; }
}
.similar-op-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.similar-op-name {
  font-weight: 600;
  font-size: 14px;
}
.similar-op-score {
  margin-left: auto;
  color: #e6a23c;
  font-size: 13px;
}
.similar-op-desc {
  color: #606266;
  font-size: 13px;
  margin-bottom: 8px;
  line-height: 1.5;
}
.similar-op-contact {
  margin-top: 4px;
}
</style>