<template>
  <div class="pipeline-page">
    <div class="toolbar">
      <div class="toolbar-left">
        <el-button type="primary" @click="showImportDialog = true">
          <el-icon><UploadFilled /></el-icon> 导入流程
        </el-button>
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

    <div class="pipeline-sections">
      <div v-for="section in pipelineSections" :key="section.type" class="pipeline-section">
        <div class="section-header">
          <span class="section-title">
            <el-icon><component :is="section.icon" /></el-icon>
            {{ section.title }}
          </span>
          <el-tag size="small" :type="section.tagType" round>{{ section.list.length }} 个</el-tag>
        </div>
        <div class="op-grid" v-if="section.list.length">
          <el-card v-for="pl in section.list" :key="pl.id" class="operator-card" shadow="hover">
            <template #header>
              <div class="card-header">
                <span class="op-name">{{ pl.display_name || pl.name }}</span>
                <el-tag size="small" :type="section.tagType">{{ section.type === 'analysis' ? '数据分析' : '数据处理' }}</el-tag>
              </div>
            </template>
            <p class="op-desc">{{ pl.description || '暂无描述' }}</p>
            <div class="op-meta">
              <el-tag v-if="pl.is_builtin" size="small" type="warning" effect="dark">内置</el-tag>
              <el-tag v-if="pl.skill_calls?.length" size="small" type="info" effect="plain">
                调用 {{ pl.skill_calls.length }} 个 Skill
              </el-tag>
              <el-tag v-else size="small" type="info" effect="plain">无 Skill 依赖</el-tag>
              <el-tag v-if="pl.source_skill_id" size="small" type="warning" effect="plain">从 Skill 生成</el-tag>
            </div>
            <div v-if="pl.parameters?.some((p: any) => p.default !== undefined)" class="op-params">
              <el-tag
                v-for="p in pl.parameters.filter((p: any) => p.default !== undefined)"
                :key="p.name"
                size="small"
                type="success"
                effect="plain"
              >
                {{ p.name }}={{ formatParamValue(p.default) }}
              </el-tag>
            </div>
            <div class="op-actions">
              <div class="op-actions-row">
                <el-button v-if="!pl.is_builtin" size="small" type="primary" @click="viewCode(pl)">
                  <el-icon><Document /></el-icon> 查看
                </el-button>
                <el-button v-if="!pl.is_builtin" size="small" type="success" plain @click="openDebug(pl)">
                  <el-icon><VideoPlay /></el-icon> 调试
                </el-button>
                <el-button v-if="!pl.is_builtin" size="small" @click="clonePipeline(pl)">
                  <el-icon><CopyDocument /></el-icon> 另存
                </el-button>
                <el-button v-if="!pl.is_builtin" size="small" @click="downloadPipeline(pl)">
                  <el-icon><Download /></el-icon> 导出
                </el-button>
                <el-button v-if="pl.is_builtin" size="small" type="info" plain disabled>
                  <el-icon><Tools /></el-icon> 内置流程
                </el-button>
                <el-button v-if="!pl.is_builtin" size="small" type="danger" plain @click="deletePipeline(pl)">
                  <el-icon><Delete /></el-icon> 删除
                </el-button>
              </div>
            </div>
          </el-card>
        </div>
        <el-empty v-else :description="`暂无${section.title}`" />
      </div>
    </div>

    <!-- 导入流程对话框 -->
    <el-dialog v-model="showImportDialog" title="导入流程" width="480px">
      <el-alert type="info" :closable="false" style="margin-bottom:16px">
        <template #title>
          请上传 .json 格式的流程文件，包含 main_code、parameters 等字段
        </template>
      </el-alert>
      <el-upload
        drag
        :show-file-list="false"
        :before-upload="validateJson"
        :http-request="handleImportJson"
        accept=".json"
      >
        <el-icon style="font-size: 48px"><UploadFilled /></el-icon>
        <div class="upload-text">拖拽或点击上传 .json 文件</div>
      </el-upload>
      <template #footer>
        <el-button @click="showImportDialog = false">取消</el-button>
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
            <span>流程说明</span>
            <div>
              <el-button size="small" text type="warning" @click="openScheduleDialog">
                <el-icon><Clock /></el-icon> 调度设置
              </el-button>
              <el-button size="small" text type="primary" @click="refreshPipelineScript" :loading="saving">
                <el-icon><Refresh /></el-icon> 刷新
              </el-button>
            </div>
          </div>

          <div v-if="debugPipeline?.description" class="pipeline-desc">{{ debugPipeline.description }}</div>
          <el-alert v-else type="info" :closable="false" style="margin-bottom: 4px"><template #title>暂无描述</template></el-alert>

          <div v-if="debugPipeline?.source_skill_id" class="pipeline-source">
            <el-tag size="small" type="warning" effect="plain">从 Skill 生成</el-tag>
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
              <div v-if="typeof p === 'object' && p.default !== undefined" class="param-default">固化值: {{ formatParamValue(p.default) }}</div>
            </div>
          </div>

          <div v-if="debugPipeline?.entry_function === '_pipeline_entry'" class="param-group">
            <div class="group-title">固化参数</div>
            <div class="fixed-params-list">
              <div v-for="p in fixedParamList" :key="p.name" class="fixed-param-row">
                <span class="fixed-param-name">{{ p.name }}</span>
                <span class="fixed-param-value">{{ formatParamValue(p.value) }}</span>
              </div>
              <div v-if="!fixedParamList.length" class="fixed-param-empty">无法解析固化参数，请查看下方代码</div>
            </div>
            <el-alert type="success" :closable="false" style="margin-top: 8px">
              <template #title>参数已固化，直接点击执行</template>
            </el-alert>
          </div>

          <div v-if="debugPipeline?.entry_function !== '_pipeline_entry'" class="param-group">
            <div class="group-title">输入参数 (JSON)</div>
            <el-input
              v-model="debugInputs"
              type="textarea"
              :rows="8"
              placeholder='{"datasource_name": "...", "table_name": "..."}'
              style="font-family: 'Consolas', monospace; font-size: 13px"
            />
          </div>

          <el-button type="primary" @click="runDebug" :loading="plStreaming" :disabled="plStreaming" style="width: 100%; margin-top: 8px">
            <el-icon><CaretRight /></el-icon> 执行调试
          </el-button>

          <el-collapse class="debug-code-collapse">
            <el-collapse-item name="code">
              <template #title>
                <span class="collapse-label">流程代码</span>
              </template>
              <pre class="debug-code-block" v-html="highlightedDebugCode"></pre>
            </el-collapse-item>
          </el-collapse>
        </div>

        <div class="debug-right">
          <div class="debug-chat-header">
            <el-icon><ChatDotRound /></el-icon>
            <span>AI 调试助手</span>
            <el-button
              size="small"
              plain
              type="danger"
              style="margin-left: auto"
              :disabled="plStreaming || debugMessages.length === 0"
              @click="clearPipelineDebugHistory"
            >
              <el-icon><Delete /></el-icon> 清空记录
            </el-button>
          </div>
          <div class="debug-message-list" ref="debugMsgListRef" @scroll="onDebugListScroll">
            <div v-if="debugMessages.length === 0 && !plStreaming" class="debug-empty">
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
                <div v-if="msg.role === 'user'" class="debug-msg-user">
                  {{ msg.content }}
                  <el-button text size="small" @click="copyText(msg.content)" class="msg-copy-btn"><el-icon><CopyDocument /></el-icon></el-button>
                </div>
                <div v-else class="debug-msg-assistant">
                  <div v-if="msg.thinking" class="debug-msg-thinking">
                    <div class="thinking-header" @click="msg.thinkingOpen = !msg.thinkingOpen">
                      <el-icon class="thinking-toggle" :class="{ open: msg.thinkingOpen }"><CaretRight /></el-icon>
                      <span>推理过程<span v-if="msg.model" class="thinking-model">{{ msg.model }}</span></span>
                      <el-button text size="small" @click.stop="copyText(msg.thinking)" class="msg-copy-btn"><el-icon><CopyDocument /></el-icon></el-button>
                    </div>
                    <div v-show="msg.thinkingOpen" class="thinking-body">{{ msg.thinking }}</div>
                  </div>
                  <el-collapse v-if="msg.content" :model-value="msg._contentOpen === false ? [] : ['content']" @change="(v: any) => { msg._contentOpen = v.length > 0 }">
                    <el-collapse-item name="content">
                      <template #title>
                        <span class="collapse-label">AI回复</span>
                        <el-button text size="small" @click.stop="copyText(msg.content)" class="collapse-copy-btn"><el-icon><CopyDocument /></el-icon> 复制</el-button>
                      </template>
                      <div class="debug-msg-content markdown-body" v-html="renderMarkdown(msg.content)"></div>
                    </el-collapse-item>
                  </el-collapse>
                  <div v-if="msg.executingMsg" class="debug-msg-executing">
                    <el-icon class="thinking-spin"><Loading /></el-icon>
                    <span>{{ msg.executingMsg }}</span>
                  </div>
                  <div class="debug-msg-time" v-if="msg.created_at">{{ formatMsgTime(msg.created_at) }}</div>
                  <div v-if="msg.runResult" class="debug-msg-runresult">
                    <div class="runresult-header">
                      <el-tag :type="msg.runResult.success ? 'success' : 'danger'" size="small">
                        {{ msg.runResult.success ? '执行成功' : '执行失败' }}
                      </el-tag>
                      <span v-if="msg.runResult.execution_time_ms" class="exec-time">{{ msg.runResult.execution_time_ms }}ms</span>
                    </div>
                    <div v-if="msg.runResult.error" class="debug-result-error">
                      <el-collapse>
                        <el-collapse-item>
                          <template #title>
                            <span class="collapse-label">错误信息</span>
                            <el-button text size="small" @click.stop="copyText(msg.runResult.error)" class="collapse-copy-btn"><el-icon><CopyDocument /></el-icon> 复制</el-button>
                          </template>
                          <pre>{{ msg.runResult.error }}</pre>
                        </el-collapse-item>
                      </el-collapse>
                    </div>
                    <div v-if="msg.runResult.stdout" class="debug-result-stdout">
                      <el-collapse>
                        <el-collapse-item>
                          <template #title>
                            <span class="collapse-label">运行日志</span>
                            <el-button text size="small" @click="copyText(msg.runResult.stdout)" class="collapse-copy-btn"><el-icon><CopyDocument /></el-icon> 复制</el-button>
                          </template>
                          <pre>{{ msg.runResult.stdout }}</pre>
                        </el-collapse-item>
                      </el-collapse>
                    </div>
                    <div v-if="msg.runResult.result != null" class="debug-result-data">
                      <el-collapse>
                        <el-collapse-item>
                          <template #title>
                            <span class="collapse-label">返回结果</span>
                            <el-button text size="small" @click.stop="copyText(formatResult(msg.runResult.result))" class="collapse-copy-btn"><el-icon><CopyDocument /></el-icon> 复制</el-button>
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
                          <span class="collapse-label">数据检查报告</span>
                          <el-button text size="small" @click.stop="copyText(msg.inspectionReport)" class="collapse-copy-btn"><el-icon><CopyDocument /></el-icon> 复制</el-button>
                        </template>
                        <div class="debug-msg-content markdown-body" v-html="renderMarkdown(msg.inspectionReport)"></div>
                      </el-collapse-item>
                    </el-collapse>
                  </div>
                  <div v-if="msg.scriptUpdated" class="debug-msg-script-updated">
                    <el-tag type="warning" size="small">代码已更新: {{ msg.scriptUpdated }}</el-tag>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="plStreaming && !debugMessages.length" class="debug-message assistant">
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

    <!-- 调度设置对话框 -->
    <el-dialog v-model="showScheduleDialog" title="调度设置" width="520px">
      <el-alert v-if="existingSchedule" type="warning" :closable="false" style="margin-bottom: 16px">
        <template #title>该流程已有调度配置，保存将更新现有调度</template>
      </el-alert>
      <el-form label-width="100px" class="schedule-dialog-form">
        <el-form-item label="调度名称" required>
          <el-input v-model="scheduleForm.name" />
        </el-form-item>
        <el-form-item label="运行模式">
          <el-radio-group v-model="scheduleForm.run_mode">
            <el-radio value="normal">普通运行</el-radio>
            <el-radio value="auto_fix">自修复运行</el-radio>
          </el-radio-group>
          <div class="form-hint">{{ scheduleForm.run_mode === 'auto_fix' ? '执行失败时自动修复代码，走双智能体检查' : '直接执行流程脚本' }}</div>
        </el-form-item>
        <el-form-item label="调度方式">
          <el-radio-group v-model="scheduleForm.schedule_type">
            <el-radio value="cron">定时</el-radio>
            <el-radio value="interval">周期</el-radio>
            <el-radio value="continuous">永久在线</el-radio>
          </el-radio-group>
        </el-form-item>

        <!-- 定时：可视化选择，支持多个时间点 -->
        <template v-if="scheduleForm.schedule_type === 'cron'">
          <el-form-item label="执行时间">
            <div class="cron-times">
              <div v-for="(t, i) in cronTimes" :key="i" class="cron-time-row">
                <el-time-select v-model="cronTimes[i]" start="00:00" step="00:15" end="23:45" placeholder="选择时间" style="width: 120px" />
                <el-button v-if="cronTimes.length > 1" size="small" text type="danger" @click="cronTimes.splice(i, 1)">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </div>
              <el-button size="small" text type="primary" @click="cronTimes.push('12:00')">
                <el-icon><Plus /></el-icon> 添加时间
              </el-button>
            </div>
          </el-form-item>
          <el-form-item label="重复频率">
            <el-select v-model="cronFrequency" style="width: 120px">
              <el-option label="每天" value="daily" />
              <el-option label="每周" value="weekly" />
              <el-option label="每月" value="monthly" />
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
        <el-form-item v-if="scheduleForm.schedule_type === 'interval'" label="执行间隔">
          <div class="interval-row">
            <el-input-number v-model="scheduleIntervalValue" :min="1" />
            <el-select v-model="scheduleIntervalUnit" style="width: 90px">
              <el-option label="秒" :value="1" />
              <el-option label="分钟" :value="60" />
              <el-option label="小时" :value="3600" />
              <el-option label="天" :value="86400" />
            </el-select>
          </div>
        </el-form-item>

        <!-- 永久在线 -->
        <el-form-item v-if="scheduleForm.schedule_type === 'continuous'" label="说明">
          <span class="form-hint">流程执行完成后自动重新启动，保持持续运行。并发数为 1，不会重叠执行。</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showScheduleDialog = false">取消</el-button>
        <el-button v-if="existingSchedule" type="danger" plain @click="deleteSchedule">删除调度</el-button>
        <el-button type="primary" @click="saveSchedule" :loading="scheduleSaving">保存</el-button>
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
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Search, VideoPlay, Document, CopyDocument,
  Delete, Download, CaretRight, ChatDotRound, Promotion, VideoPause, Refresh,
  UploadFilled, Loading, Clock, Plus, Tools, CircleCheck,
  DataLine, DataAnalysis,
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
import { formatTime } from '@/utils/time'

hljs.registerLanguage('python', python)

const md = markdownIt({ html: false, breaks: true, linkify: true })
function renderMarkdown(text: string): string {
  return md.render(text || '')
}
function formatMsgTime(ts?: string): string {
  return formatTime(ts)
}

function copyText(text: string) {
  navigator.clipboard.writeText(text).then(() => ElMessage.success('已复制')).catch(() => ElMessage.error('复制失败'))
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
  is_builtin?: boolean
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
  executingMsg?: string
  created_at?: string
}

const pipelines = ref<Pipeline[]>([])
const searchText = ref('')

function isAnalysisPipeline(pl: any): boolean {
  const tags: any[] = pl?.tags || []
  return tags.some((t: any) => String(t) === 'skill_type:analysis')
}

function applySearch(list: any[]) {
  if (!searchText.value) return list
  const q = searchText.value.toLowerCase()
  return list.filter(
    (pl: any) =>
      (pl.name || '').toLowerCase().includes(q) ||
      (pl.display_name || '').toLowerCase().includes(q) ||
      (pl.description || '').toLowerCase().includes(q)
  )
}

const processingPipelines = computed(() => applySearch(pipelines.value.filter((pl: any) => !isAnalysisPipeline(pl))))
const analysisPipelines = computed(() => applySearch(pipelines.value.filter((pl: any) => isAnalysisPipeline(pl))))
const pipelineSections = computed(() => [
  { type: 'processing', title: '数据处理流程', icon: DataLine, tagType: 'primary', list: processingPipelines.value },
  { type: 'analysis', title: '数据分析流程', icon: DataAnalysis, tagType: 'success', list: analysisPipelines.value },
])
const showImportDialog = ref(false)
const importing = ref(false)
const showCodeDrawer = ref(false)
const codePipeline = ref<Pipeline | null>(null)
const executions = ref<Execution[]>([])
const detailTab = ref('code')
const flowCanvasRef = ref<HTMLElement | null>(null)
const saving = ref(false)

const highlightedCode = computed(() => {
  if (!codePipeline.value?.main_code) return ''
  return hljs.highlight(codePipeline.value.main_code, { language: 'python' }).value
})

const highlightedDebugCode = computed(() => {
  if (!debugPipeline.value?.main_code) return ''
  return hljs.highlight(debugPipeline.value.main_code, { language: 'python' }).value
})

const fixedParamList = computed<{ name: string; value: any }[]>(() => {
  if (!debugPipeline.value || debugPipeline.value.entry_function !== '_pipeline_entry') return []
  const code = debugPipeline.value.main_code || ''

  // 非 argparse: return main(**{...})
  const dictMatch = code.match(/return\s+main\(\*\*(\{[^}]*\})\s*\)/)
  if (dictMatch) {
    try {
      const jsonStr = dictMatch[1]
        .replace(/\bTrue\b/g, 'true')
        .replace(/\bFalse\b/g, 'false')
        .replace(/\bNone\b/g, 'null')
        .replace(/'/g, '"')
      const obj = JSON.parse(jsonStr)
      return Object.entries(obj).map(([name, value]) => ({ name, value }))
    } catch { /* fall through */ }
  }

  // argparse: _sys.argv = ['script', '--key', 'value', ...]
  const argvMatch = code.match(/_sys\.argv\s*=\s*\[([^\]]*)\]/)
  if (argvMatch) {
    try {
      const argv = JSON.parse('[' + argvMatch[1].replace(/'/g, '"') + ']')
      const params: { name: string; value: any }[] = []
      for (let i = 0; i < argv.length; i++) {
        if (typeof argv[i] === 'string' && argv[i].startsWith('--')) {
          const name = argv[i].slice(2)
          const next = argv[i + 1]
          if (next !== undefined && (typeof next !== 'string' || !next.startsWith('--'))) {
            params.push({ name, value: next })
            i++
          } else {
            params.push({ name, value: true })
          }
        }
      }
      if (params.length) return params
    } catch { /* fall through */ }
  }

  // 兜底: parameters 数组中有 default 的
  const params = debugPipeline.value.parameters || []
  return params
    .filter((p: any) => typeof p === 'object' && p.default !== undefined)
    .map((p: any) => ({ name: p.name, value: p.default }))
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

function validateJson(file: any): boolean {
  if (!file.name.toLowerCase().endsWith('.json')) {
    ElMessage.error('只能上传 .json 文件')
    return false
  }
  return true
}

async function handleImportJson(options: any) {
  const file = options.file as File
  importing.value = true
  try {
    const text = await file.text()
    const data = JSON.parse(text)
    if (!data.main_code && !data.name) {
      ElMessage.error('JSON 文件缺少必要字段（name 或 main_code）')
      return
    }
    const payload = {
      name: data.name || 'imported_pipeline',
      display_name: data.display_name || data.name || '',
      description: data.description || '',
      main_code: data.main_code || '',
      entry_function: data.entry_function || 'main',
      parameters: data.parameters || [],
      skill_calls: data.skill_calls || [],
      tags: data.tags || [],
      category: data.category || null,
      visibility: data.visibility || 'private',
    }
    const res = await api.post('/pipelines/import', payload)
    ElMessage.success(`流程 "${(res as any).display_name || (res as any).name}" 导入成功`)
    showImportDialog.value = false
    await loadPipelines()
  } catch (e: any) {
    if (e instanceof SyntaxError) {
      ElMessage.error('JSON 解析失败，请检查文件格式')
    } else {
      ElMessage.error(e.response?.data?.detail || '导入失败')
    }
  } finally {
    importing.value = false
  }
}

async function loadPipelines() {
  try {
    const params: any = {}
    if (searchText.value) params.search = searchText.value
    pipelines.value = await api.get('/pipelines', { params }) as any
  } catch {
    ElMessage.error('加载流程列表失败')
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
  const data = {
    name: pl.name || 'pipeline',
    display_name: pl.display_name || pl.name || '',
    description: pl.description || '',
    main_code: pl.main_code || '',
    entry_function: pl.entry_function || 'main',
    parameters: pl.parameters || [],
    skill_calls: pl.skill_calls || [],
    tags: pl.tags || [],
    category: pl.category || null,
    visibility: pl.visibility || 'private',
  }
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${pl.name || 'pipeline'}.json`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
  ElMessage.success('流程已导出')
}

async function deletePipeline(pl: Pipeline) {
  if (pl.is_builtin) { ElMessage.warning('内置流程不可删除'); return }
  try {
    await ElMessageBox.confirm(`确定删除 "${pl.display_name || pl.name}"？`, '确认删除', { type: 'warning' })
    await api.delete(`/pipelines/${pl.id}`)
    ElMessage.success('已删除')
    await loadPipelines()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
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

const DEBUG_MSG_MAX = 50

function loadPipelineDebugMsgs(plId: string | number): DebugMessage[] {
  try {
    const raw = localStorage.getItem(`dc_pipeline_debug_msgs_${plId}`)
    if (!raw) return []
    return JSON.parse(raw).map((m: any) => ({ ...m, thinkingOpen: false, executingMsg: undefined, executingMsgs: undefined }))
  } catch { return [] }
}

function savePipelineDebugMsgs(plId: string | number, msgs: DebugMessage[]) {
  try {
    const stripped = msgs.slice(-DEBUG_MSG_MAX).map(m => ({ ...m, executingMsg: undefined, executingMsgs: undefined, thinkingOpen: false }))
    localStorage.setItem(`dc_pipeline_debug_msgs_${plId}`, JSON.stringify(stripped))
  } catch {
    try {
      const lite = msgs.slice(-DEBUG_MSG_MAX).map(m => ({ role: m.role, content: m.content, llmContent: m.llmContent, scriptUpdated: m.scriptUpdated, model: m.model, created_at: m.created_at }))
      localStorage.setItem(`dc_pipeline_debug_msgs_${plId}`, JSON.stringify(lite))
    } catch { /* quota exceeded */ }
  }
}

let _plDebugSaveTimer: ReturnType<typeof setTimeout> | null = null
let _plDebugSaveId: string | number | null = null
function scheduleSavePipelineDebug() {
  if (!debugPipeline.value) return
  _plDebugSaveId = (debugPipeline.value as any).id
  if (_plDebugSaveTimer) clearTimeout(_plDebugSaveTimer)
  _plDebugSaveTimer = setTimeout(() => {
    if (_plDebugSaveId != null) savePipelineDebugMsgs(_plDebugSaveId, debugMessages.value)
  }, 500)
}
function flushPipelineDebugSave() {
  if (_plDebugSaveTimer) {
    clearTimeout(_plDebugSaveTimer)
    _plDebugSaveTimer = null
    if (_plDebugSaveId != null && debugMessages.value.length > 0) savePipelineDebugMsgs(_plDebugSaveId, debugMessages.value)
  }
}

watch(debugMessages, scheduleSavePipelineDebug, { deep: true })

const signatureParams = computed(() => {
  if (debugPipeline.value?.entry_function === '_pipeline_entry') return ''
  const params = debugPipeline.value?.parameters as any[] | undefined
  if (!params || !params.length) return 'inputs'
  return params.map(p => {
    const name = typeof p === 'string' ? p : p.name
    const required = typeof p === 'object' ? p.required !== false : true
    return required ? name : `${name}=...`
  }).join(', ')
})

function formatParamValue(v: any): string {
  if (v === null || v === undefined) return ''
  if (Array.isArray(v)) return v.join(',')
  if (typeof v === 'object') return JSON.stringify(v)
  const s = String(v)
  return s.length > 30 ? s.slice(0, 30) + '...' : s
}
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
  flushPipelineDebugSave()
  debugPipeline.value = { ...pl }
  debugMessages.value = loadPipelineDebugMsgs((pl as any).id)
  debugInput.value = ''

  if (pl.entry_function === '_pipeline_entry') {
    debugInputs.value = '{}'
  } else {
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
  }

  debugDrawer.value = true
  debugPinnedToBottom.value = true
}

async function clearPipelineDebugHistory() {
  try {
    await ElMessageBox.confirm('确认清空当前流程的调试记录？此操作不可撤销。', '提示', { type: 'warning' })
  } catch { return }
  if (debugPipeline.value) {
    localStorage.removeItem(`dc_pipeline_debug_msgs_${(debugPipeline.value as any).id}`)
  }
  debugMessages.value = []
  ElMessage.success('已清空调试记录')
}

function resetDebug() {
  flushPipelineDebugSave()
  debugPipeline.value = null
  if (debugAbortController) {
    debugAbortController.abort()
    debugAbortController = null
  }
  plStreaming.value = false
  debugMessages.value = []
}

function handleDebugBeforeClose(done: () => void) {
  if (plStreaming.value) {
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
  if (!debugPipeline.value || plStreaming.value) return
  debugInput.value = '执行流程并检查结果'
  await handleDebugSend()
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

  debugMessages.value.push({ role: 'user', content: userMsg, created_at: new Date().toISOString() })
  debugInput.value = ''
  plStreaming.value = true
  debugAbortController = new AbortController()

  const assistantIdx = debugMessages.value.length
  debugMessages.value.push({ role: 'assistant', content: '', llmContent: '', thinking: '', thinkingOpen: false, created_at: new Date().toISOString() })
  debugPinnedToBottom.value = true
  await nextTick()
  scrollDebugToBottom(true)

  let scriptChanged = false
  let streamOk = false

  try {
    const token = localStorage.getItem('access_token')
    const history = debugMessages.value.slice(0, assistantIdx - 1).map(m => ({
      role: m.role,
      content: (m.llmContent != null ? m.llmContent : m.content) + (m.runResult ? `\n\n[执行结果: ${m.runResult.success ? '成功' : '失败'}]` + (m.runResult.error ? ` 错误: ${m.runResult.error}` : '') : '') + (m.scriptUpdated ? `\n\n[代码已更新: ${m.scriptUpdated}]` : ''),
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
          } else if (data.type === 'ping') {
            // SSE 心跳，忽略
          } else if (data.type === 'clear_thinking') {
            msg.thinking = ''
            msg.content = ''
            msg.llmContent = ''
            msg.thinkingOpen = false
            thinkingDone = false
          } else if (data.type === 'thinking') {
            if (thinkingDone && msg.thinking) {
              msg.thinking += '\n\n--- 新一轮推理 ---\n'
              msg.thinkingOpen = false
              thinkingDone = false
            }
            if (!msg.thinking) msg.thinkingOpen = false
            msg.thinking = (msg.thinking || '') + data.content
            scrollThinkingBodyToBottom(assistantIdx)
          } else if (data.type === 'content') {
            if (!thinkingDone && msg.thinking) { thinkingDone = true; msg.thinkingOpen = false; }
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
          } else if (data.type === 'executing') {
            msg.executingMsg = data.message || '正在执行流程...'
            if (!thinkingDone && msg.thinking) { thinkingDone = true; msg.thinkingOpen = false }
          } else if (data.type === 'run_result') {
            msg.executingMsg = ''
            if (!thinkingDone && msg.thinking) { thinkingDone = true; msg.thinkingOpen = false }
            const r = data.result || {}
            const inner = typeof r.result === 'object' && r.result ? r.result : {}
            const failed = !r.success || inner.success === false || (r.error && String(r.error).trim()) || (inner.error && String(inner.error).trim())
            msg.runResult = { ...r, success: !failed, error: r.error || inner.error || '' }
            if (failed) {
              const errMsg = String(r.error || inner.error || '未知错误').substring(0, 300)
              msg.content += `\n❌ 执行失败：${errMsg}\n`
            } else if (!msg.content) {
              msg.content = '流程执行完成'
            }
          } else if (data.type === 'script_updated') {
            msg.scriptUpdated = data.script_name
            scriptChanged = true
            try {
              const fresh = await api.get(`/pipelines/${debugPipeline.value!.id}`)
              debugPipeline.value = fresh as any
            } catch { /* skip */ }
          } else if (data.type === 'error') {
            msg.content += `\n\n错误: ${data.content || '未知错误'}`
          } else if (data.type === 'inspection_report') {
            msg.inspectionReport = data.report
          } else if (data.type === 'inspecting') {
            msg.executingMsg = ''
            msg.content += `\n\n🔍 ${data.message || 'DataInspector 正在检查数据质量...'}\n`
            msg.thinkingOpen = false
            thinkingDone = true
          } else if (data.type === 'retry') {
            msg.executingMsg = ''
            msg.content += `\n\n---\n🔄 ${data.message || '开始修复...'}\n`
            msg.thinkingOpen = false
            thinkingDone = true
          } else if (data.type === 'round') {
            msg.executingMsg = ''
            msg.thinkingOpen = false
            thinkingDone = true
            const _label = data.action === 'execute' ? '执行' : '修改'
            msg.content += `\n\n─── 第${data.round}次${_label} ───\n`
          } else if (data.type === 'give_up') {
            msg.executingMsg = ''
            msg.content += `\n\n⚠ **修复失败**${data.reason ? '\n' + data.reason : '——无法自动修复'}`
          } else if (data.type === 'fatal') {
            msg.executingMsg = ''
            const issues = data.issues || []
            let fatalText = `\n\n🚫 **致命问题——数据违反法律法规，已停止处理**\n\n${data.summary || ''}\n`
            for (const issue of issues) {
              fatalText += `\n- [FATAL] ${issue.description || ''}`
              if (issue.suggestion) fatalText += `\n  → ${issue.suggestion}`
            }
            msg.content += fatalText
          } else if (data.type === 'warning_confirmation') {
            msg.executingMsg = ''
            const issues = data.issues || []
            let warnText = `\n\n⚠ **检查发现以下警告问题，是否需要修复？**\n\n${data.summary || ''}\n`
            for (const issue of issues) {
              warnText += `\n- [WARNING] ${issue.description || ''}`
              if (issue.column) warnText += ` (列: ${issue.column})`
              if (issue.suggestion) warnText += `\n  → ${issue.suggestion}`
            }
            warnText += '\n\n> 如需修复，请回复"修复警告问题"'
            msg.content += warnText
          } else if (data.type === 'platform_issue') {
            msg.executingMsg = ''
            msg.content += `\n\n🔧 **平台能力缺失——这不是脚本问题，修改脚本无法解决**\n\n${data.message || ''}\n`
            msg.thinkingOpen = false
            thinkingDone = true
          } else if (data.type === 'done') {
            msg.executingMsg = ''
            if (!msg.content || msg.content.trim() === '') {
              msg.content = '✅ 调试完成'
            } else if (!msg.content.includes('✅') && !msg.content.includes('⚠') && !msg.content.includes('🔧') && !msg.content.includes('🚫')) {
              msg.content += '\n\n✅ 调试完成'
            }
            msg.thinkingOpen = false
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
      debugMessages.value[assistantIdx].content = `请求出错: ${e.message === 'network error' || e.message === 'Failed to fetch' ? '连接异常，请检查后端是否正常运行' : e.message || String(e)}`
    }
  } finally {
    plStreaming.value = false
    debugAbortController = null
    await nextTick()
    scrollDebugToBottom()
  }
}

// ==================== 调度设置 ====================
const showScheduleDialog = ref(false)
const existingSchedule = ref<any>(null)
const scheduleSaving = ref(false)
const scheduleIntervalValue = ref(5)
const scheduleIntervalUnit = ref(60)
const cronTimes = ref<string[]>(['08:00'])
const cronFrequency = ref('daily')
const cronWeekdays = ref<number[]>([1])
const cronMonthDay = ref(1)

const scheduleForm = ref({
  name: '',
  run_mode: 'normal',
  schedule_type: 'cron',
  cron_expression: '',
})

const cronHumanReadable = computed(() => {
  const times = cronTimes.value.filter(t => t).map(t => {
    const [h, m] = t.split(':')
    return `${h.padStart(2,'0')}:${m.padStart(2,'0')}`
  })
  if (!times.length) return ''
  const timeStr = times.join('、')
  if (cronFrequency.value === 'daily') return `每天 ${timeStr}`
  if (cronFrequency.value === 'weekly') {
    const names = ['一','二','三','四','五','六','日']
    const days = cronWeekdays.value.map(d => '周' + names[d-1]).join('、')
    return `每${days} ${timeStr}`
  }
  if (cronFrequency.value === 'monthly') return `每月${cronMonthDay.value}号 ${timeStr}`
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

async function openScheduleDialog() {
  if (!debugPipeline.value) return
  const pipeName = debugPipeline.value.display_name || debugPipeline.value.name || '流程'
  scheduleForm.value = {
    name: pipeName + '_调度',
    run_mode: 'normal',
    schedule_type: 'cron',
    cron_expression: '',
  }
  cronTimes.value = ['08:00']
  cronFrequency.value = 'daily'
  cronWeekdays.value = [1]
  cronMonthDay.value = 1
  scheduleIntervalValue.value = 5
  scheduleIntervalUnit.value = 60
  existingSchedule.value = null

  try {
    const all: any[] = await api.get('/schedules', { params: { limit: 200 } }) as any
    const found = all.find((s: any) => s.task_target_id === debugPipeline.value!.id)
    if (found) {
      existingSchedule.value = found
      scheduleForm.value.name = found.name
      scheduleForm.value.run_mode = found.run_mode || 'normal'
      scheduleForm.value.schedule_type = found.schedule_type === 'manual' ? 'cron' : found.schedule_type
      if (found.cron_expression) {
        scheduleForm.value.cron_expression = found.cron_expression
        parseCronExpression(found.cron_expression)
      }
      if (found.interval_seconds) {
        if (found.interval_seconds >= 86400 && found.interval_seconds % 86400 === 0) { scheduleIntervalValue.value = found.interval_seconds / 86400; scheduleIntervalUnit.value = 86400 }
        else if (found.interval_seconds >= 3600 && found.interval_seconds % 3600 === 0) { scheduleIntervalValue.value = found.interval_seconds / 3600; scheduleIntervalUnit.value = 3600 }
        else if (found.interval_seconds >= 60 && found.interval_seconds % 60 === 0) { scheduleIntervalValue.value = found.interval_seconds / 60; scheduleIntervalUnit.value = 60 }
        else { scheduleIntervalValue.value = found.interval_seconds; scheduleIntervalUnit.value = 1 }
      }
    }
  } catch {}
  showScheduleDialog.value = true
}

async function saveSchedule() {
  if (!debugPipeline.value) return
  if (!scheduleForm.value.name) { ElMessage.warning('请填写调度名称'); return }
  scheduleSaving.value = true
  try {
    const payload: any = {
      name: scheduleForm.value.name,
      task_type: 'pipeline',
      task_target_id: debugPipeline.value.id,
      run_mode: scheduleForm.value.run_mode,
    }
    if (scheduleForm.value.schedule_type === 'cron') {
      payload.schedule_type = 'cron'
      payload.cron_expression = buildCronExpression()
    } else if (scheduleForm.value.schedule_type === 'interval') {
      payload.schedule_type = 'interval'
      payload.interval_seconds = scheduleIntervalValue.value * scheduleIntervalUnit.value
    } else if (scheduleForm.value.schedule_type === 'continuous') {
      payload.schedule_type = 'interval'
      payload.interval_seconds = 1
    }
    if (existingSchedule.value) {
      await api.put(`/schedules/${existingSchedule.value.id}`, payload)
    } else {
      await api.post('/schedules', payload)
    }
    ElMessage.success('调度已保存')
    showScheduleDialog.value = false
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    scheduleSaving.value = false
  }
}

async function deleteSchedule() {
  if (!existingSchedule.value) return
  try {
    await ElMessageBox.confirm('删除该调度配置？', '确认', { type: 'warning' })
    await api.delete(`/schedules/${existingSchedule.value.id}`)
    ElMessage.success('调度已删除')
    showScheduleDialog.value = false
    existingSchedule.value = null
  } catch (e: any) { if (e !== 'cancel') ElMessage.error('删除失败') }
}

const route = useRoute()

onMounted(async () => {
  await loadPipelines()
  const debugId = route.query.debug as string
  if (debugId) {
    const pl = pipelines.value.find((p: any) => p.id === debugId)
    if (pl) {
      openDebug(pl)
      const instruction = route.query.instruction ? decodeURIComponent(route.query.instruction as string) : ''
      if (instruction) {
        debugInput.value = instruction
      }
    }
  }
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
  flex-wrap: wrap;

  .toolbar-left { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
  .toolbar-right { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
}

.pipeline-sections {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.pipeline-section {
  .section-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 12px;
    padding-bottom: 8px;
    border-bottom: 2px solid var(--el-border-color-lighter);
    .section-title {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 16px;
      font-weight: 600;
      color: var(--el-text-color-primary);
    }
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
  }
  .op-meta {
    margin: 8px 0;
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    min-height: 26px;
  }
  .op-params {
    margin: 4px 0 8px;
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
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
  height: 75vh;
}

.debug-left {
  width: 420px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  gap: 8px;
}

.pipeline-desc {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
  background: #f5f7fa;
  border-radius: 6px;
  padding: 10px 14px;
  white-space: pre-wrap;
  word-break: break-word;
}

.pipeline-source {
  display: flex;
  gap: 4px;
}

.form-hint { font-size: 12px; color: #909399; margin-top: 4px; display: block; width: 100%; padding-left: 0; }
.cron-times { display: flex; flex-direction: column; gap: 6px; }
.cron-time-row { display: flex; align-items: center; gap: 6px; }
.interval-row { display: flex; gap: 8px; align-items: center; }

.schedule-dialog-form .el-radio-group {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.schedule-dialog-form .el-radio {
  margin-right: 0;
}

.debug-code-collapse {
  margin-top: 8px;
  border-top: 1px solid #e4e7ed;

  .collapse-label {
    font-weight: 600;
    font-size: 13px;
    color: #303133;
  }

  .debug-code-block {
    font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
    font-size: 12px;
    line-height: 1.5;
    background: #1e1e1e;
    color: #d4d4d4;
    border-radius: 6px;
    padding: 12px;
    overflow-x: auto;
    max-height: 400px;
    overflow-y: auto;
    margin: 0;
  }
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
  .param-default {
    font-size: 12px;
    color: #67c23a;
    padding-left: 2px;
    margin-top: 2px;
  }
}

.fixed-params-list {
  background: #f0f9eb;
  border: 1px solid #e1f3d8;
  border-radius: 6px;
  padding: 8px 12px;
}
.fixed-param-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 3px 0;
  font-size: 13px;
  border-bottom: 1px dashed #e1f3d8;
  &:last-child { border-bottom: none; }
}
.fixed-param-name {
  color: #606266;
  flex-shrink: 0;
  margin-right: 12px;
}
.fixed-param-value {
  color: #67c23a;
  font-family: 'Consolas', 'Monaco', monospace;
  text-align: right;
  word-break: break-all;
}
.fixed-param-empty {
  font-size: 12px;
  color: #909399;
  text-align: center;
  padding: 4px 0;
}

.debug-msg-executing {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 0;
  font-size: 13px;
  color: #909399;

  .thinking-spin {
    animation: rotate 1.2s linear infinite;
  }
}

@keyframes rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
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
  .exec-time { font-size: 11px; color: #909399; }

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
    position: sticky;
    top: 0;
    z-index: 10;
    background: #f5f7fa;
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
