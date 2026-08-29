<template>
  <div class="chat-container">
    <!-- 会话列表侧边栏 -->
    <div class="session-sidebar">
      <el-button class="new-session-btn" @click="handleNewSession">
        <el-icon><Plus /></el-icon> 新建会话
      </el-button>
      <div class="session-list">
        <div
          v-for="session in chatStore.sessions"
          :key="session.id"
          class="session-item"
          :class="{ active: session.id === chatStore.currentSessionId }"
          @click="chatStore.switchSession(session.id)"
        >
          <el-icon><ChatDotRound /></el-icon>
          <span class="session-title">{{ session.title || '新会话' }}</span>
          <el-dropdown trigger="click" @command="(cmd: string) => handleSessionCommand(cmd, session.id)">
            <el-icon class="session-more" @click.stop><MoreFilled /></el-icon>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="rename">重命名</el-dropdown-item>
                <el-dropdown-item command="export">导出对话</el-dropdown-item>
                <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
    </div>

    <!-- 对话主区域 -->
    <div class="chat-main">
      <div v-if="!chatStore.currentSessionId" class="empty-chat">
        <el-icon :size="64" color="#ccc"><ChatDotRound /></el-icon>
        <h2>开始新对话</h2>
        <p>输入自然语言描述，AI将帮你处理数据</p>
      </div>
      <template v-else>
        <!-- 顶部工具栏 -->
        <div class="chat-toolbar">
          <span class="chat-toolbar-title">{{ currentSessionTitle || '新会话' }}</span>
          <div class="chat-toolbar-actions">
            <el-button
              class="export-btn"
              size="small"
              :icon="Download"
              :disabled="chatStore.messages.length === 0"
              @click="handleExportCurrent"
            >
              导出对话
            </el-button>
            <el-button
              class="clear-history-btn"
              size="small"
              :icon="Delete"
              :disabled="chatStore.isStreaming || chatStore.messages.length === 0"
              @click="handleClearMessages"
            >
              清空记录
            </el-button>
          </div>
        </div>
        <!-- 消息流 -->
        <div class="message-list" ref="messageListRef">
          <div
            v-for="msg in chatStore.messages"
            :key="msg.id"
            class="message-item"
            :class="msg.role"
          >
            <div class="message-avatar">
              <el-avatar :size="36" v-if="msg.role === 'assistant'" style="background:#409eff">{{ agentName }}</el-avatar>
              <el-avatar :size="36" v-else>我</el-avatar>
            </div>
              <div class="message-content">
              <!-- 推理过程（默认折叠，点击展开） -->
              <div v-if="msg.role === 'assistant' && msg.reasoning" class="reasoning-section">
                <div class="reasoning-header" @click="toggleReasoning(msg.id)">
                  <el-icon :class="{ 'is-rotated': reasoningExpanded[msg.id] }"><CaretRight /></el-icon>
                  <span>推理过程</span>
                  <el-tag v-if="msg.model" size="small" type="info">{{ msg.model }}</el-tag>
                </div>
                <div v-show="reasoningExpanded[msg.id]" class="reasoning-content">
                  <div class="reasoning-text" v-html="renderMarkdown(msg.reasoning)"></div>
                </div>
              </div>
              <!-- 执行进度（可折叠，默认展开） -->
              <div v-if="msg.role === 'assistant' && msg.executingMsgs && msg.executingMsgs.length" class="executing-indicator">
                <div class="executing-toggle" @click="msg._execCollapsed = !msg._execCollapsed">
                  <el-icon v-if="!msg._execCollapsed"><ArrowDown /></el-icon>
                  <el-icon v-else><ArrowRight /></el-icon>
                  <span>{{ msg.executingMsgs.length }} 条进度信息</span>
                </div>
                <div v-show="!msg._execCollapsed">
                  <div v-for="(m, i) in msg.executingMsgs" :key="i" class="executing-line">
                    <el-icon v-if="i === msg.executingMsgs.length - 1 && chatStore.isStreaming" class="is-loading"><Loading /></el-icon>
                    <el-icon v-else class="executing-dot"><CircleCheck /></el-icon>
                    <span>{{ msg.agentName && i === msg.executingMsgs.length - 1 ? `[${msg.agentName}] ` : '' }}{{ m }}</span>
                  </div>
                </div>
              </div>
              
              <!-- 技能/流程/数据匹配建议（可能多个同时出现） -->
              <template v-if="msg.role === 'assistant'">
              <div v-for="(sug, sugIdx) in (msg.suggestions || (msg.suggestion ? [msg.suggestion] : []))" :key="sugIdx" class="suggestion-card">
                <template v-if="sug.type === 'data_suggestion'">
                  <div class="suggestion-header">
                    <el-icon><Coin /></el-icon>
                    <span>检测到相关数据（共 {{ sug.matches.length }} 个），请选择要使用的数据</span>
                  </div>
                  <div v-for="m in suggestionPageFor(sug, sugIdx)" :key="m._idx" class="suggestion-item">
                    <div class="suggestion-item-name">{{ m.datasource_name }} → {{ m.table_name }}</div>
                    <div class="suggestion-item-meta">
                      <span v-if="m.row_count != null" class="meta-row">行数: {{ m.row_count?.toLocaleString() }}</span>
                      <span v-if="m.column_count != null" class="meta-col">列数: {{ m.column_count }}</span>
                    </div>
                    <div class="suggestion-actions">
                      <el-button v-if="m.can_use" type="primary" size="small" @click="selectData(msg, m)">选择此数据</el-button>
                      <el-button v-if="m.can_use" size="small" @click="viewTable(m)">查看数据</el-button>
                      <el-button v-else type="warning" size="small" @click="requestPermission('datasource', m.datasource_id, m)">申请数据权限</el-button>
                    </div>
                  </div>
                  <div v-if="sug.matches.length > 3" class="suggestion-pager">
                    <el-button size="small" :disabled="suggestionPageIdxFor(sugIdx) === 0" @click="suggestionPrevFor(sugIdx)">上一页</el-button>
                    <span class="pager-info">{{ suggestionPageIdxFor(sugIdx) + 1 }}/{{ Math.ceil(sug.matches.length / 3) }}</span>
                    <el-button size="small" :disabled="(suggestionPageIdxFor(sugIdx) + 1) * 3 >= sug.matches.length" @click="suggestionNextFor(sugIdx)">下一页</el-button>
                  </div>
                  <div class="suggestion-actions" style="margin-top: 8px;">
                    <el-button size="small" @click="abandonDataSuggestion(msg, sug, sugIdx)">放弃选择</el-button>
                  </div>
                </template>
                <template v-else-if="sug.type === 'target_suggestion'">
                  <div class="suggestion-header">
                    <el-icon><WarningFilled /></el-icon>
                    <span>检测到目标表已存在（共 {{ sug.matches.length }} 个），可能已处理过</span>
                  </div>
                  <div v-for="m in suggestionPageFor(sug, sugIdx)" :key="m._idx" class="suggestion-item">
                    <div class="suggestion-item-name">{{ m.datasource_name }} → {{ m.table_name }}</div>
                    <div class="suggestion-item-meta">
                      <span v-if="m.row_count != null" class="meta-row">行数: {{ m.row_count?.toLocaleString() }}</span>
                      <span v-if="m.column_count != null" class="meta-col">列数: {{ m.column_count }}</span>
                    </div>
                    <div class="suggestion-actions">
                      <el-button v-if="m.can_use" type="primary" size="small" @click="selectTargetTable(msg, m, sugIdx)">选择此数据</el-button>
                      <el-button v-if="m.can_use" size="small" @click="viewTable(m)">查看数据</el-button>
                    </div>
                    <!-- 选中后显示写入策略 -->
                    <div v-if="msg._selectedTarget === sugIdx + '_' + m._idx" class="target-write-mode">
                      <el-radio-group v-model="msg._writeMode" size="small">
                        <el-radio-button label="overwrite">覆盖</el-radio-button>
                        <el-radio-button label="append">追加</el-radio-button>
                        <el-radio-button label="direct">直接使用</el-radio-button>
                      </el-radio-group>
                      <el-button v-if="msg._writeMode" type="primary" size="small" style="margin-left: 8px;" @click="confirmTargetTable(msg, m)">{{ msg._writeMode === 'direct' ? '确认使用' : '确认' }}</el-button>
                    </div>
                  </div>
                  <!-- 不选择：新建目标表 -->
                  <div class="suggestion-actions" style="margin-top: 8px;">
                    <span style="font-size: 12px; color: #909399;">新建目标表：</span>
                    <el-input v-model="msg._newTableName" size="small" placeholder="输入新表名" style="width: 200px;" :value="msg._newTableName || generateTableName(msg)"></el-input>
                  </div>
                </template>
                <template v-else-if="sug.type === 'skill_suggestion'">
                  <div class="suggestion-header">
                    <el-icon><MagicStick /></el-icon>
                    <span>检测到匹配{{ (sug.matches[0]?.type === 'pipeline') ? '流程' : '技能' }}（共 {{ sug.matches.length }} 个）</span>
                  </div>
                  <div v-for="m in suggestionPageFor(sug, sugIdx)" :key="m._idx" class="suggestion-item">
                    <div class="suggestion-item-name">{{ m.name }}</div>
                    <div class="suggestion-item-desc">{{ m.description }}</div>
                    <div class="suggestion-actions" style="gap: 8px;">
                      <el-button v-if="m.can_use" type="primary" size="small" :disabled="!isParamsReady(msg, sug)" @click="useMatched(m, msg)">使用技能</el-button>
                      <el-button v-if="m.can_use" type="primary" size="small" :disabled="!isParamsReady(msg, sug)" @click="debugSkill(m, msg)">调试技能</el-button>
                      <el-button v-if="!m.can_use" type="warning" size="small" @click="requestPermission(m.type, m.id, m)">申请权限</el-button>
                    </div>
                  </div>
                  <div v-if="sug.matches.length > 3" class="suggestion-pager">
                    <el-button size="small" :disabled="suggestionPageIdxFor(sugIdx) === 0" @click="suggestionPrevFor(sugIdx)">上一页</el-button>
                    <span class="pager-info">{{ suggestionPageIdxFor(sugIdx) + 1 }}/{{ Math.ceil(sug.matches.length / 3) }}</span>
                    <el-button size="small" :disabled="(suggestionPageIdxFor(sugIdx) + 1) * 3 >= sug.matches.length" @click="suggestionNextFor(sugIdx)">下一页</el-button>
                  </div>
                  <div class="suggestion-actions" style="margin-top: 8px; gap: 8px;">
                    <el-button type="primary" size="small" @click="goCreateSkill(msg)">创建新技能</el-button>
                    <el-button type="primary" size="small" @click="continueProcessing(msg)">{{ sug.msg_type === 'analysis' ? '直接分析' : '直接处理' }}</el-button>
                  </div>
                </template>
                <!-- skill_no_match 渲染卡片，其余 no_match 类型提示在 content 里不渲染卡片 -->
                <template v-else-if="sug.type === 'skill_no_match'">
                  <div class="suggestion-header">
                    <el-icon><WarningFilled /></el-icon>
                    <span>未找到匹配的技能</span>
                  </div>
                  <div class="suggestion-actions" style="margin-top: 8px; gap: 8px;">
                    <el-button type="primary" size="small" @click="goCreateSkill(msg)">创建新技能</el-button>
                    <el-button type="primary" size="small" @click="continueProcessing(msg)">{{ sug.msg_type === 'analysis' ? '直接分析' : '直接处理' }}</el-button>
                  </div>
                </template>
              </div>
              </template>
                <!-- 主要内容 -->
              <div v-if="msg.role === 'assistant' && msg.content" class="markdown-content" v-html="renderMarkdown(msg.content)"></div>
              <div v-else-if="msg.role === 'assistant' && chatStore.isStreaming && (!msg.executingMsgs || !msg.executingMsgs.length) && !msg.inspectionReport" class="typing-indicator">
                <span></span><span></span><span></span>
              </div>
              <!-- 数据检查报告 -->
              <div v-if="msg.role === 'assistant' && msg.inspectionReport" class="inspection-report-section">
                <el-collapse model-value="report">
                  <el-collapse-item name="report">
                    <template #title>
                      <el-icon style="margin-right: 4px;"><CircleCheck /></el-icon>
                      <span class="collapse-label">数据检查报告</span>
                    </template>
                    <div class="markdown-content" v-html="renderMarkdown(msg.inspectionReport)"></div>
                  </el-collapse-item>
                </el-collapse>
              </div>
              <div v-if="msg.role === 'user' && msg.attachments && msg.attachments.length" class="user-attachments">
                <div
                  v-for="att in msg.attachments"
                  :key="att.filename"
                  class="user-attachment-card"
                  @click="reuseAttachment(att)"
                  title="点击重新引用此文件"
                >
                  <el-icon class="att-icon"><Document /></el-icon>
                  <div class="att-info">
                    <div class="att-name">{{ att.filename }}</div>
                    <div class="att-meta" v-if="att.sheets && att.sheets.length">{{ att.sheets.length }} 个工作表</div>
                  </div>
                  <el-icon class="att-reuse"><RefreshRight /></el-icon>
                </div>
              </div>
              <div v-if="msg.role === 'user'" class="user-text">{{ msg.content }}</div>
              
              <div class="msg-time" v-if="msg.created_at">{{ formatMsgTime(msg.created_at) }}</div>
              <div class="message-actions">
                <el-button
                  class="copy-btn"
                  :icon="CopyDocument"
                  circle
                  size="small"
                  @click="handleCopy(msg.content)"
                  title="复制"
                />
              </div>
            </div>
          </div>
        </div>

        <!-- 输入区域 -->
        <div class="chat-input-wrap">
          <div v-if="attachments.length" class="attachment-bar">
            <el-tag
              v-for="att in attachments"
              :key="att.filename"
              closable
              type="info"
              size="small"
              @close="removeAttachment(att.filename)"
            >
              <el-icon style="vertical-align: middle; margin-right: 2px;"><Document /></el-icon>
              {{ att.filename }}
              <span v-if="att.sheets.length" style="color: #909399; margin-left: 4px;">
                ({{ att.sheets.length }} 表)
              </span>
            </el-tag>
          </div>
          <div v-if="chatStore.selectedData" class="selected-data-bar">
            <el-tag
              v-if="chatStore.selectedData.target_datasource_name"
              closable
              type="success"
              size="default"
              @close="chatStore.selectedData = null"
            >
              <el-icon style="vertical-align: middle; margin-right: 2px;"><Coin /></el-icon>
              {{ chatStore.selectedData.target_datasource_name }} → {{ chatStore.selectedData.target_table_name }}
            </el-tag>
            <el-tag
              v-else-if="chatStore.selectedData.datasource_name"
              closable
              type="success"
              size="default"
              @close="chatStore.selectedData = null"
            >
              <el-icon style="vertical-align: middle; margin-right: 2px;"><Coin /></el-icon>
              {{ chatStore.selectedData.datasource_name }} → {{ chatStore.selectedData.table_name }}
            </el-tag>
          </div>
          <div class="input-area">
            <el-input
              v-model="inputText"
              type="textarea"
              :rows="2"
              :autosize="{ minRows: 1, maxRows: 6 }"
              :disabled="chatStore.isStreaming"
              placeholder="输入消息... (Enter发送, Shift+Enter换行, ↑↓浏览历史)"
              @keydown="handleKeyDown"
            />
            <div class="input-actions">
              <el-upload
                :show-file-list="false"
                :http-request="handleUpload"
                accept=".xlsx,.xls"
                :disabled="chatStore.isStreaming || uploading"
              >
                <el-button
                  circle
                  :loading="uploading"
                  :disabled="chatStore.isStreaming"
                  title="上传 Excel 附件（≤5MB）"
                >
                  <el-icon v-if="!uploading"><Paperclip /></el-icon>
                </el-button>
              </el-upload>
              <el-button
                v-if="chatStore.isStreaming"
                type="danger"
                circle
                @click="chatStore.stopGeneration()"
              >
                <el-icon><VideoPause /></el-icon>
              </el-button>
              <el-button
                v-else
                type="primary"
                circle
                :disabled="!inputText.trim() && attachments.length === 0"
                @click="handleSend"
              >
                <el-icon><Promotion /></el-icon>
              </el-button>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useChatStore } from '@/stores/chat'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CopyDocument, Delete, Download, Loading, CircleCheck, Paperclip, Document, RefreshRight, CaretRight, MagicStick, Coin, InfoFilled, WarningFilled } from '@element-plus/icons-vue'
import MarkdownIt from 'markdown-it'
import * as echarts from 'echarts'
import api from '@/api/index'
import { chatApi } from '@/api/chat'

const router = useRouter()
const chatStore = useChatStore()
const inputText = ref('')
const messageListRef = ref<HTMLElement>()
const reasoningExpanded = ref<Record<string, boolean>>({})
const agentName = ref('DC')

// 聊天附件：所有上传的 Excel 归一到「聊天上传」虚拟数据源，发送消息时把文件名列表传给后端
interface Attachment {
  filename: string          // 原始文件名，作为附件唯一标识
  table_name_prefix: string // 表名前缀（basename without extension）
  sheets: string[]
}
const attachments = ref<Attachment[]>([])
const uploading = ref(false)

// 输入历史（↑↓ 浏览）— 按会话 ID 隔离
const inputHistory = ref<string[]>([])
const historyIdx = ref(-1)
const savedDraft = ref('')

function loadInputHistory(sessionId: string | null) {
  if (!sessionId) { inputHistory.value = []; return }
  try { inputHistory.value = JSON.parse(localStorage.getItem(`dc_chat_history_${sessionId}`) || '[]') } catch { inputHistory.value = [] }
  historyIdx.value = -1
}

const currentSessionTitle = computed(() => {
  const s = chatStore.sessions.find((s) => s.id === chatStore.currentSessionId)
  return s?.title || ''
})

const md = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
  typographer: true,
})

// chart 块计数器（每个 chart 块需要唯一 id）
let _chartBlockSeq = 0
// 待渲染的 chart 块映射：domId -> spec
const _pendingChartBlocks = ref<Record<string, any>>({})

function renderMarkdown(content: string): string {
  if (!content) return ''
  // 提取 <chart type="..." title="..." x_label="..." y_label="...">{json}</chart> 块
  const chartRegex = /<chart\s+([^>]*)>([\s\S]*?)<\/chart>/g
  const charts: Array<{ id: string; spec: any }> = []
  let cleaned = content.replace(chartRegex, (match, attrs, jsonStr) => {
    // 解析属性
    const typeMatch = attrs.match(/type="([^"]*)"/)
    const titleMatch = attrs.match(/title="([^"]*)"/)
    const xLabelMatch = attrs.match(/x_label="([^"]*)"/)
    const yLabelMatch = attrs.match(/y_label="([^"]*)"/)
    const type = typeMatch ? typeMatch[1] : 'bar'
    const title = titleMatch ? titleMatch[1] : ''
    const xLabel = xLabelMatch ? xLabelMatch[1] : ''
    const yLabel = yLabelMatch ? yLabelMatch[1] : ''

    // 解析 JSON 数据
    let data: any = null
    try {
      data = JSON.parse(jsonStr.trim())
    } catch (e) {
      return `<div class="echart-error">⚠️ 图表数据解析失败: ${(e as Error).message}</div>`
    }

    // 构造 ECharts option
    const spec = buildEchartsOption(type, title, xLabel, yLabel, data)
    const id = `echart-${_chartBlockSeq++}`
    charts.push({ id, spec })
    _pendingChartBlocks.value[id] = spec
    return `<div class="echart-block" id="${id}"></div>`
  })
  return md.render(cleaned)
}

function buildEchartsOption(type: string, title: string, xLabel: string, yLabel: string, data: any): any {
  const categories = data.categories || []
  const series = data.series || [{ name: title || '数据', values: data.values || [] }]
  const option: any = {
    title: title ? { text: title, left: 'center' } : undefined,
    tooltip: { trigger: type === 'pie' ? 'item' : 'axis' },
    legend: series.length > 1 ? { data: series.map((s: any) => s.name), bottom: 0 } : undefined,
    grid: { left: '3%', right: '4%', bottom: series.length > 1 ? '12%' : '3%', containLabel: true },
  }
  if (type === 'pie') {
    option.series = [{
      type: 'pie',
      radius: '60%',
      data: categories.map((c: string, i: number) => ({ name: c, value: (data.values || [])[i] || 0 })),
    }]
  } else if (type === 'line') {
    option.xAxis = { type: 'category', data: categories, name: xLabel }
    option.yAxis = { type: 'value', name: yLabel }
    option.series = series.map((s: any) => ({
      name: s.name, type: 'line', data: s.values || [], smooth: true,
    }))
  } else {
    // bar（柱状图，默认）
    option.xAxis = { type: 'category', data: categories, name: xLabel }
    option.yAxis = { type: 'value', name: yLabel }
    option.series = series.map((s: any) => ({
      name: s.name, type: 'bar', data: s.values || [],
    }))
  }
  return option
}

// 渲染所有待处理的 chart 块
function renderPendingChartBlocks() {
  for (const [id, spec] of Object.entries(_pendingChartBlocks.value)) {
    const el = document.getElementById(id)
    if (el && !el.hasChildNodes()) {
      try {
        const chart = echarts.init(el)
        chart.setOption(spec)
      } catch (e) {
        console.error('echarts init failed:', id, e)
      }
      delete _pendingChartBlocks.value[id]
    }
  }
}

function formatMsgTime(ts: string): string {
  try {
    const d = new Date(ts.endsWith('Z') ? ts : ts + 'Z')
    return d.toLocaleString('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      hour12: false,
    })
  } catch { return '' }
}

function toggleReasoning(msgId: string) {
  reasoningExpanded.value[msgId] = !reasoningExpanded.value[msgId]
}

// 点击历史消息里的文件卡片，重新引用该文件
function reuseAttachment(att: { filename: string; table_name_prefix?: string; sheets?: string[] }) {
  const exists = attachments.value.some(a => a.filename === att.filename)
  if (exists) {
    ElMessage.info(`${att.filename} 已在附件列表中`)
    return
  }
  attachments.value.push({
    filename: att.filename,
    table_name_prefix: att.table_name_prefix || '',
    sheets: att.sheets || [],
  })
  ElMessage.success(`已引用: ${att.filename}`)
}

async function handleCopy(content: string) {
  try {
    await navigator.clipboard.writeText(content)
    ElMessage.success('已复制到剪贴板')
  } catch {
    const textarea = document.createElement('textarea')
    textarea.value = content
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
    ElMessage.success('已复制到剪贴板')
  }
}

function scrollToBottom(smooth = true) {
  nextTick(() => {
    if (messageListRef.value) {
      messageListRef.value.scrollTo({
        top: messageListRef.value.scrollHeight,
        behavior: smooth ? 'smooth' : 'auto'
      })
    }
  })
}

async function loadAgentConfig() {
  try {
    const config = await api.get('/chat/agent/config')
    if (config && config.short_name) {
      agentName.value = config.short_name
    }
  } catch (e) {
    // 使用默认值
  }
}

onMounted(async () => {
  try {
    await Promise.all([
      chatStore.fetchSessions(),
      loadAgentConfig()
    ])

    // 如果有会话，自动选中第一个并滚动到底部
    if (chatStore.sessions.length > 0 && !chatStore.currentSessionId) {
      await chatStore.switchSession(chatStore.sessions[0].id)
    }
    // 显式加载当前会话的输入历史（watch 只在切换时触发，首次进入需手动加载）
    loadInputHistory(chatStore.currentSessionId)
  } catch {
    // 后端可能正在 reload（开发模式改代码触发 uvicorn 重启），静默处理
  }

  // 初始化时滚动到底部 + 渲染 chart 块
  scrollToBottom(false)
  nextTick(() => renderPendingChartBlocks())
})

// 监听消息变化，自动滚动到底部 + 渲染 chart 块
watch(
  () => chatStore.messages.length,
  () => {
    scrollToBottom()
    nextTick(() => renderPendingChartBlocks())
  }
)

// 监听流式内容变化，实时滚动 + 渲染 chart 块
watch(
  () => [chatStore.streamingContent, chatStore.streamingReasoning],
  () => {
    // 流式更新使用即时滚动，避免 smooth 动画被高频 token 打断
    scrollToBottom(false)
    // 渲染 chart 块（DOM 更新后）
    nextTick(() => renderPendingChartBlocks())
  }
)

// 监听会话切换，滚动到底部 + 加载该会话的输入历史
watch(
  () => chatStore.currentSessionId,
  (newId) => {
    loadInputHistory(newId)
    nextTick(() => {
      scrollToBottom(false)
    })
  }
)

async function handleNewSession() {
  await chatStore.createSession()
  reasoningExpanded.value = {}
}

  reasoningExpanded.value = {}

  async function handleSend() {
  if (chatStore.isStreaming) return
  if (!inputText.value.trim() && attachments.value.length === 0) return
  const text = inputText.value
  const atts = attachments.value.map(a => ({ filename: a.filename, table_name_prefix: a.table_name_prefix, sheets: a.sheets }))
  // 保存到输入历史（按会话 ID 隔离）
  const _sid = chatStore.currentSessionId
  if (_sid) {
    inputHistory.value.push(text)
    if (inputHistory.value.length > 50) inputHistory.value = inputHistory.value.slice(-50)
    try { localStorage.setItem(`dc_chat_history_${_sid}`, JSON.stringify(inputHistory.value)) } catch {}
  }
  historyIdx.value = -1
  inputText.value = ''
  attachments.value = []
  // 用户不点「选择」也不点「继续」→ 说明之前的匹配结果不对，重新匹配，不跳过任何步骤
  const _autoSkip: string[] = []
  await chatStore.sendMessage(text, atts.length ? atts : undefined, undefined, _autoSkip.length ? _autoSkip : undefined)
}

// ===== 匹配建议导航 =====
const _suggestionPages = ref<Record<string, number>>({})

function suggestionPage(msg: any) {
  if (!msg.suggestion?.matches) return []
  const idx = _suggestionPages.value[msg.id] || 0
  const start = idx * 3
  return msg.suggestion.matches.slice(start, start + 3).map((m: any, i: number) => ({ ...m, _idx: start + i }))
}

function suggestionPageIdx(msg: any) {
  return _suggestionPages.value[msg.id] || 0
}

function suggestionPrev(msg: any) {
  const idx = _suggestionPages.value[msg.id] || 0
  if (idx > 0) _suggestionPages.value[msg.id] = idx - 1
}

function suggestionNext(msg: any) {
  const idx = _suggestionPages.value[msg.id] || 0
  _suggestionPages.value[msg.id] = idx + 1
}

// 多 suggestion 分页（按 suggestion 索引）
function suggestionPageFor(sug: any, sugIdx: number) {
  if (!sug?.matches) return []
  const key = `${sugIdx}`
  const idx = _suggestionPages.value[key] || 0
  const start = idx * 3
  return sug.matches.slice(start, start + 3).map((m: any, i: number) => ({ ...m, _idx: start + i }))
}

function suggestionPageIdxFor(sugIdx: number) {
  return _suggestionPages.value[`${sugIdx}`] || 0
}

function suggestionPrevFor(sugIdx: number) {
  const key = `${sugIdx}`
  const idx = _suggestionPages.value[key] || 0
  if (idx > 0) _suggestionPages.value[key] = idx - 1
}

function suggestionNextFor(sugIdx: number) {
  const key = `${sugIdx}`
  const idx = _suggestionPages.value[key] || 0
  _suggestionPages.value[key] = idx + 1
}

function useMatched(m: any, msg: any) {
  // 使用技能：存技能到 selectedData，走 classify 路径生成技能调用指令
  const allMsgs = chatStore.messages
  const msgIdx = allMsgs.findIndex(x => x === msg)
  const userText = msgIdx > 0 ? (allMsgs[msgIdx - 1]?.content || '') : ''
  chatStore.selectedData = {
    ...chatStore.selectedData,
    skill_id: m.id,
    skill_name: m.name,
    skill_type: m.type,
  } as any
  const atts = (allMsgs[msgIdx - 1] as any)?.attachments?.map((a: any) => ({ filename: a.filename, table_name_prefix: a.table_name_prefix, sheets: a.sheets })) || []
  // 清空旧回复内容，保留 suggestions 卡片
  msg.content = ''
  msg.executingMsgs = []
  msg.agentName = ''
  msg.inspectionReport = ''
  // 走 directExecute（复用消息不弹用户消息），use_skill=true 让后端走技能调试模式
  chatStore.sendMessage(userText, atts.length ? atts : undefined, true, false, true)
}

function debugSkill(m: any, msg: any) {
  // 调试技能：跳转到技能/流程调试页面
  const allMsgs = chatStore.messages
  const msgIdx = allMsgs.findIndex(x => x === msg)
  const userText = msgIdx > 0 ? (allMsgs[msgIdx - 1]?.content || '') : ''
  const sel = chatStore.selectedData
  const sessionId = chatStore.currentSessionId || ''
  const query: Record<string, string> = { debug: m.id }
  const _dsName = sel?.datasource_name || m.datasource_name || ''
  const _tblName = sel?.table_name || m.table_name || ''
  const _tgtDsName = sel?.target_datasource_name || ''
  const _tgtTblName = sel?.target_table_name || ''
  if (_dsName) query.ds_name = _dsName
  if (_tblName) query.table_name = _tblName
  if (_tgtDsName) query.target_ds_name = _tgtDsName
  if (_tgtTblName) query.target_table_name = _tgtTblName
  if (sessionId) query.chat_session_id = sessionId
  query.instruction = encodeURIComponent(userText)
  if (m.type === 'pipeline') {
    window.open(router.resolve({ path: '/pipeline', query }).href, '_blank')
  } else {
    window.open(router.resolve({ path: '/skill', query }).href, '_blank')
  }
}

function viewTable(m: any) {
  window.open(router.resolve({ path: '/config', query: { tab: 'datasource', ds: m.datasource_id, table: m.table_name } }).href, '_blank')
}

function updateParamsHint(msg: any) {
  const sel = chatStore.selectedData
  const ready: string[] = []
  const hasSource = !!sel?.datasource_id && !!sel?.table_name
  if (sel?.datasource_name) ready.push(`源数据源: ${sel.datasource_name}`)
  if (sel?.table_name) ready.push(`源表: ${sel.table_name}`)
  if (sel?.target_datasource_name) ready.push(`目标数据源: ${sel.target_datasource_name}`)
  if (sel?.target_table_name) ready.push(`目标表: ${sel.target_table_name}`)
  if (sel?.skill_name) ready.push(`技能: ${sel.skill_name}`)
  const missing: string[] = []
  if (!hasSource) {
    if (!sel?.datasource_id) missing.push('源数据源')
    if (!sel?.table_name) missing.push('源数据表')
  }
  if (msg.suggestions) {
    const hasTarget = (msg.suggestions as any[]).some(s => s.type === 'target_suggestion' || s.type === 'target_table_no_match' || s.type === 'target_datasource_no_match')
    if (hasTarget) {
      if (!sel?.target_datasource_id) missing.push('目标数据源')
      if (!sel?.target_table_name) missing.push('目标数据表')
    }
  }
  let hint = '检测到匹配结果，请选择操作。'
  if (ready.length) hint += '\n\n✅ 已确定参数：' + ready.join('，')
  if (missing.length) hint += '\n\n⚠️ 还缺：' + missing.join('、') + '，请补充'
  msg.content = hint
  chatStore.messages = [...chatStore.messages]
}

function selectData(msg: any, m: any) {
  chatStore.selectedData = {
    ...chatStore.selectedData,
    datasource_id: m.datasource_id,
    datasource_name: m.datasource_name,
    table_name: m.table_name,
  } as any
  ElMessage.success(`已选择数据：${m.datasource_name} → ${m.table_name}`)
  updateParamsHint(msg)
  nextTick(() => {
    const textarea = document.querySelector('.input-area textarea') as HTMLTextAreaElement
    if (textarea) textarea.focus()
  })
}

function abandonDataSuggestion(msg: any, sug: any, sugIdx: number) {
  chatStore.selectedData = null
  updateParamsHint(msg)
  msg.content = (msg.content ? msg.content + '\n\n' : '') + '没有您想要的数据吗？请再描述一下数据的详细特征'
  chatStore.messages = [...chatStore.messages]
  nextTick(() => {
    const textarea = document.querySelector('.input-area textarea') as HTMLTextAreaElement
    if (textarea) textarea.focus()
  })
}

function selectTargetTable(msg: any, m: any, sugIdx: number) {
  msg._selectedTarget = sugIdx + '_' + m._idx
  msg._writeMode = ''
}

function confirmTargetTable(msg: any, m: any) {
  const mode = msg._writeMode
  if (mode === 'direct') {
    chatStore.selectedData = {
      ...chatStore.selectedData,
      target_datasource_id: m.datasource_id,
      target_datasource_name: m.datasource_name,
      target_table_name: m.table_name,
      target_write_mode: 'direct',
    } as any
    ElMessage.success(`已选择直接使用目标表：${m.datasource_name} → ${m.table_name}`)
    updateParamsHint(msg)
    return
  }
  chatStore.selectedData = {
    ...chatStore.selectedData,
    target_datasource_id: m.datasource_id,
    target_datasource_name: m.datasource_name,
    target_table_name: m.table_name,
    target_write_mode: mode,
  } as any
  ElMessage.success(`已选择目标表：${m.datasource_name} → ${m.table_name}（${mode === 'overwrite' ? '覆盖' : '追加'}）`)
  updateParamsHint(msg)
  nextTick(() => {
    const textarea = document.querySelector('.input-area textarea') as HTMLTextAreaElement
    if (textarea) textarea.focus()
  })
}

// 检查参数是否齐全（用于控制"使用技能"和"调试技能"按钮是否可点）
function isParamsReady(msg: any, sug: any): boolean {
  const sel = chatStore.selectedData
  const hasSource = !!sel?.datasource_id && !!sel?.table_name
  if (sug?.msg_type === 'analysis') {
    return hasSource
  }
  return hasSource && (!!sel?.target_datasource_id || !!msg._newTableName)
}

function getMissingParams(msg: any, sug: any): string[] {
  const sel = chatStore.selectedData
  const missing = []
  if (!sel?.datasource_id) missing.push('源数据源')
  if (!sel?.table_name) missing.push('源数据表')
  if (sug?.msg_type !== 'analysis') {
    if (!sel?.target_datasource_id && !msg._newTableName) missing.push('目标数据表')
  }
  return missing
}

function generateTableName(msg: any) {
  if (!msg._newTableName) {
    const now = new Date()
    const ts = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`
    msg._newTableName = `result_${ts}`
  }
  return msg._newTableName
}

function goCreateSkill(msg: any) {
  const allMsgs = chatStore.messages
  const msgIdx = allMsgs.findIndex(m => m === msg)
  const userText = msgIdx > 0 ? (allMsgs[msgIdx - 1]?.content || '') : ''
  // 组装已选数据上下文 + 用户需求
  const parts = []
  const sel = chatStore.selectedData
  if (sel?.datasource_name) parts.push(`数据源: ${sel.datasource_name}`)
  if (sel?.table_name) parts.push(`表名: ${sel.table_name}`)
  if (sel?.target_datasource_name) parts.push(`目标数据源: ${sel.target_datasource_name}`)
  if (sel?.target_table_name) parts.push(`目标表名: ${sel.target_table_name}`)
  if (userText) parts.push(`需求: ${userText}`)
  const desc = encodeURIComponent(parts.join('\n'))
  router.push({ path: '/skill', query: { create: 'true', desc } })
}

async function continueProcessing(msg: any) {
  const allMsgs = chatStore.messages
  const msgIdx = allMsgs.findIndex(m => m === msg)
  if (msgIdx < 1) return
  const userMsg = allMsgs[msgIdx - 1]
  const text = userMsg?.content || ''
  if (!text) return
  const atts = (userMsg as any)?.attachments?.map((a: any) => ({ filename: a.filename, table_name_prefix: a.table_name_prefix, sheets: a.sheets })) || []
  // 检查是否有 data_suggestion 但用户没选源表
  const hasDataSuggestion = (msg.suggestions || []).some((s: any) => s.type === 'data_suggestion')
  if (hasDataSuggestion && !chatStore.selectedData?.datasource_id) {
    ElMessage.warning('请先选择源数据表，再继续处理')
    return
  }
  // 检查 target_no_match 或 target_suggestion 时用户输入了新表名
  const hasTargetSuggestion = (msg.suggestions || []).some((s: any) => s.type === 'target_suggestion' || s.type === 'target_no_match')
  if (hasTargetSuggestion && !chatStore.selectedData?.target_datasource_id) {
    if (msg._newTableName) {
      chatStore.selectedData = {
        ...chatStore.selectedData,
        target_table_name: msg._newTableName,
        target_write_mode: 'create',
      } as any
    }
  }
  await chatStore.sendDirectly(text, atts.length ? atts : undefined)
}

async function requestPermission(resourceType: string, resourceId: string, m: any) {
  try {
    await api.post('/permissions/request', {
      resource_type: resourceType,
      resource_id: resourceId,
      requested_level: 'use',
      reason: `在对话中需要使用此${resourceType === 'datasource' ? '数据源' : resourceType === 'pipeline' ? '流程' : '技能'}`,
    })
    ElMessage.success('权限申请已提交，等待资源所有者审批')
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    if (detail && typeof detail === 'string') {
      ElMessage.warning(detail)
    } else {
      ElMessage.error('权限申请失败')
    }
  }
}

function beforeUpload(file: File): boolean {
  if (!/\.(xlsx|xls)$/i.test(file.name)) {
    ElMessage.error('只支持 Excel 文件 (.xlsx / .xls)')
    return false
  }
  if (file.size > 5 * 1024 * 1024) {
    ElMessage.error(`文件大小超过 5MB 限制（当前 ${(file.size / 1024 / 1024).toFixed(1)}MB）`)
    return false
  }
  return true
}

async function handleUpload(opt: any) {
  const file: File = opt.file
  if (!beforeUpload(file)) {
    // el-upload 的手动模式，返回 false 即可中止
    return
  }
  uploading.value = true
  try {
    const res = await chatApi.uploadAttachment(file)
    attachments.value.push({
      filename: res.filename,
      table_name_prefix: res.table_name_prefix,
      sheets: res.sheets,
    })
    ElMessage.success(`已上传: ${res.filename}（${res.sheets.length} 个工作表）`)
  } catch (e: any) {
    const detail = e?.response?.data?.detail || e?.message || String(e)
    ElMessage.error(`上传失败: ${detail}`)
  } finally {
    uploading.value = false
  }
}

function removeAttachment(filename: string) {
  attachments.value = attachments.value.filter(a => a.filename !== filename)
}

async function handleClearMessages() {
  try {
    await ElMessageBox.confirm(
      '确定清空当前会话的所有消息吗？此操作不可恢复。',
      '清空记录',
      { type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  await chatStore.clearMessages()
  reasoningExpanded.value = {}
  ElMessage.success('已清空当前会话记录')
}

function handleKeyDown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  } else if (e.key === 'ArrowUp') {
    if (inputHistory.value.length === 0) return
    e.preventDefault()
    if (historyIdx.value === -1) {
      savedDraft.value = inputText.value
      historyIdx.value = inputHistory.value.length - 1
    } else if (historyIdx.value > 0) {
      historyIdx.value--
    }
    inputText.value = inputHistory.value[historyIdx.value]
  } else if (e.key === 'ArrowDown') {
    if (historyIdx.value === -1) return
    e.preventDefault()
    if (historyIdx.value < inputHistory.value.length - 1) {
      historyIdx.value++
      inputText.value = inputHistory.value[historyIdx.value]
    } else {
      historyIdx.value = -1
      inputText.value = savedDraft.value
    }
  }
}

async function handleSessionCommand(command: string, sessionId: string) {
  if (command === 'delete') {
    await ElMessageBox.confirm('确定删除此会话？', '提示', { type: 'warning' })
    await chatStore.deleteSession(sessionId)
  } else if (command === 'rename') {
    const { value } = await ElMessageBox.prompt('请输入新名称', '重命名')
    if (value) {
      const { chatApi } = await import('@/api/chat')
      await chatApi.updateSession(sessionId, value)
      await chatStore.fetchSessions()
    }
  } else if (command === 'export') {
    await exportSession(sessionId)
  }
}

function formatExportTime(ts: string): string {
  try {
    const d = new Date(ts.endsWith('Z') ? ts : ts + 'Z')
    return d.toLocaleString('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      hour12: false,
    })
  } catch { return ts }
}

async function exportSession(sessionId: string) {
  const { chatApi } = await import('@/api/chat')
  let msgs: any[]
  if (sessionId === chatStore.currentSessionId) {
    msgs = chatStore.messages
  } else {
    msgs = await chatApi.listMessages(sessionId)
  }
  if (!msgs || msgs.length === 0) {
    ElMessage.warning('该会话没有消息可导出')
    return
  }

  const session = chatStore.sessions.find((s) => s.id === sessionId)
  const sessionTitle = session?.title || '新会话'

  const lines: string[] = []
  lines.push(`# ${sessionTitle}`)
  lines.push('')
  lines.push(`> 导出时间：${formatExportTime(new Date().toISOString())}`)
  lines.push(`> 消息数：${msgs.length}`)
  lines.push('')
  lines.push('---')
  lines.push('')

  for (const msg of msgs) {
    const role = msg.role === 'user' ? '用户' : '助手'
    const time = formatExportTime(msg.created_at)
    lines.push(`## ${role}  ${time}`)
    lines.push('')
    if (msg.model) {
      lines.push(`*模型：${msg.model}*`)
      lines.push('')
    }
    if (msg.reasoning) {
      lines.push('<details><summary>推理过程</summary>')
      lines.push('')
      lines.push(msg.reasoning)
      lines.push('')
      lines.push('</details>')
      lines.push('')
    }
    lines.push(msg.content || '')
    lines.push('')
    lines.push('---')
    lines.push('')
  }

  const content = lines.join('\n')
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  const safeTitle = sessionTitle.replace(/[\\/:*?"<>|]/g, '_')
  a.download = `${safeTitle}_${new Date().toISOString().slice(0, 10)}.md`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
  ElMessage.success(`已导出 ${msgs.length} 条对话`)
}

async function handleExportCurrent() {
  if (!chatStore.currentSessionId) return
  await exportSession(chatStore.currentSessionId)
}
</script>

<style lang="scss" scoped>
.chat-container {
  display: flex;
  height: 100%;
}

.session-sidebar {
  width: 260px;
  background: #f7f7f8;
  border-right: 1px solid #e6e6e6;
  display: flex;
  flex-direction: column;
  font-size: 14px;

  .new-session-btn {
    margin: 12px;
  }

  .session-list {
    flex: 1;
    overflow-y: auto;
  }

  .session-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 16px;
    cursor: pointer;
    border-radius: 8px;
    margin: 2px 8px;
    font-size: 13px;

    &:hover, &.active {
      background: #ececec;
    }

    .session-title {
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .session-more {
      opacity: 0;
    }

    &:hover .session-more {
      opacity: 1;
    }
  }
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #fff;
}

.chat-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 20px;
  border-bottom: 1px solid #f0f0f0;
  background: #fafafa;

  .chat-toolbar-title {
    font-size: 14px;
    font-weight: 500;
    color: #606266;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .chat-toolbar-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
  }

  .clear-history-btn,
  .export-btn {
    flex-shrink: 0;
  }
}

.empty-chat {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #999;

  h2 { margin: 16px 0 8px; color: #666; }
  p { margin: 0; }
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  scroll-behavior: smooth;
  font-size: 13px;
}

.message-item {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;

  .message-content {
    flex: 1;
    min-width: 0;
  }

  .message-actions {
    display: flex;
    gap: 8px;
    align-items: center;
    opacity: 0;
    transition: opacity 0.2s;
    margin-top: 4px;
  }

  .msg-time {
    font-size: 11px;
    color: #999;
    margin-top: 2px;
  }

  &:hover .message-actions {
    opacity: 1;
  }

  .copy-btn {
    transition: opacity 0.2s;
  }

  &.user {
    flex-direction: row-reverse;

    .message-content {
      display: flex;
      flex-direction: column;
      align-items: flex-end;

      .user-text {
        background: #409eff;
        color: #fff;
        padding: 8px 14px;
        border-radius: 12px;
        max-width: 85%;
        width: fit-content;
        word-break: break-word;
        font-size: 13px;
        line-height: 1.5;
      }
    }
  }

  &.assistant {
    .message-content {
      .markdown-content {
        max-width: 92%;
        width: fit-content;
        line-height: 1.6;
        font-size: 13px;

        :deep(pre) {
          background: #ffffff;
          color: #303133;
          border: 1px solid #ebeef5;
          padding: 16px;
          border-radius: 8px;
          overflow-x: auto;
          font-size: 13px;
        }

        :deep(code) {
          background: #f0f0f0;
          padding: 2px 6px;
          border-radius: 4px;
          font-size: 13px;
        }

        :deep(pre code) {
          background: none;
          padding: 0;
        }
      }
    }
  }
}

.reasoning-section {
  margin-bottom: 12px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  overflow: hidden;
  
  .reasoning-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: #f5f7fa;
    cursor: pointer;
    user-select: none;
    font-size: 13px;
    
    &:hover {
      background: #ecf0f5;
    }
    
    .el-icon {
      transition: transform 0.3s;
      &.is-rotated {
        transform: rotate(90deg);
      }
    }
    
    span {
      font-weight: 500;
      color: #606266;
    }
  }
  
  .reasoning-content {
    padding: 12px;
    background: #fafafa;
    border-top: 1px solid #e4e7ed;
    
    .reasoning-text {
      font-size: 14px;
      line-height: 1.6;
      color: #606266;
      
      :deep(p) {
        margin: 8px 0;
      }
      
      :deep(ul), :deep(ol) {
        padding-left: 20px;
        margin: 8px 0;
      }
      
      :deep(code) {
        background: #f0f0f0;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 13px;
      }
    }
  }
}

.inspection-report-section {
  margin: 8px 0 12px 0;
  max-width: 92%;

  .collapse-label {
    font-weight: 500;
    color: #606266;
    font-size: 13px;
  }

  :deep(.el-collapse) {
    border: 1px solid #e4e7ed;
    border-radius: 8px;
    overflow: hidden;
  }

  :deep(.el-collapse-item__header) {
    padding: 0 12px;
    background: #f5f7fa;
    font-size: 13px;
  }

  :deep(.el-collapse-item__content) {
    padding: 12px;
    background: #fafafa;
    font-size: 13px;
    line-height: 1.6;

    .markdown-content {
      max-width: 100%;
      width: 100%;

      :deep(table) {
        border-collapse: collapse;
        width: 100%;
        font-size: 12px;
      }

      :deep(th), :deep(td) {
        border: 1px solid #dcdfe6;
        padding: 4px 8px;
      }

      :deep(th) {
        background: #f0f0f0;
      }
    }

    // ECharts 图表块
    .markdown-content :deep(.echart-block) {
      width: 100%;
      height: 320px;
      margin: 12px 0;
      background: #fff;
      border: 1px solid #ebeef5;
      border-radius: 8px;
      padding: 8px;
    }

    .markdown-content :deep(.echart-error) {
      color: #f56c6c;
      background: #fef0f0;
      padding: 8px 12px;
      border-radius: 4px;
      margin: 8px 0;
      font-size: 12px;
    }
  }
}

.suggestion-card {
  background: #f0f9ff;
  border: 1px solid #d0e8ff;
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 8px;

  .suggestion-header {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 14px;
    font-weight: 600;
    color: #409eff;
    margin-bottom: 8px;
  }

  .suggestion-item {
    padding: 8px 0;
    border-top: 1px solid #e8f4ff;

    .suggestion-item-name {
      font-weight: 600;
      font-size: 13px;
    }

    .suggestion-item-meta {
      display: flex;
      gap: 12px;
      margin: 4px 0;
      font-size: 12px;
      color: #909399;

      .meta-row { color: #67c23a; }
      .meta-col { color: #909399; }
    }

    .suggestion-item-desc {
      font-size: 12px;
      color: #666;
      margin: 4px 0;
    }

    .suggestion-actions {
      display: flex;
      gap: 8px;
      margin-top: 6px;
      align-items: center;
    }

    .missing-hint {
      color: var(--el-color-warning);
      font-size: 12px;
    }

    .target-write-mode {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 6px 0;
      margin-top: 4px;
    }
  }
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 8px 0;

  span {
    width: 8px;
    height: 8px;
    background: #999;
    border-radius: 50%;
    animation: typing 1.4s infinite;

    &:nth-child(2) { animation-delay: 0.2s; }
    &:nth-child(3) { animation-delay: 0.4s; }
  }
}

.executing-indicator {
  padding: 8px 12px;
  margin: 4px 0;
  background: #f0f9ff;
  border-radius: 6px;
  color: #409eff;
  font-size: 13px;

  .executing-toggle {
    display: flex;
    align-items: center;
    gap: 4px;
    cursor: pointer;
    padding-bottom: 4px;
    color: #909399;
    font-size: 12px;
    user-select: none;

    &:hover {
      color: #409eff;
    }
  }

  .executing-line {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 2px 0;
  }

  .is-loading {
    animation: rotating 1.5s linear infinite;
  }

  .executing-dot {
    color: #67c23a;
    font-size: 12px;
  }
}

/* 用户消息文件卡片 */
.user-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;

  .user-attachment-card {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 10px;
    background: #f0f9ff;
    border: 1px solid #d9ecff;
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s;

    &:hover {
      background: #ecf5ff;
      border-color: #409eff;
      .att-reuse { opacity: 1; }
    }

    .att-icon { color: #409eff; font-size: 18px; }

    .att-info {
      .att-name { font-size: 13px; font-weight: 500; color: #303133; }
      .att-meta { font-size: 11px; color: #909399; }
    }

    .att-reuse { color: #c0c4cc; opacity: 0.6; font-size: 14px; transition: opacity 0.2s; }
  }
}

@keyframes typing {
  0%, 60%, 100% { transform: translateY(0); }
  30% { transform: translateY(-8px); }
}

.chat-input-wrap {
  border-top: 1px solid #e6e6e6;
}

.attachment-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 20px 0;
}

.selected-data-bar {
  padding: 8px 20px 0;
  display: flex;
  align-items: center;
  gap: 6px;
}

.input-area {
  padding: 16px 20px;
  display: flex;
  gap: 12px;
  align-items: flex-end;

    .el-textarea {
        flex: 1;
        font-size: 13px;
    }

  .input-actions {
    display: flex;
    gap: 8px;
  }
}
</style>
