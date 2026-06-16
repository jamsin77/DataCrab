<template>
  <div class="skill-page">
    <div class="toolbar">
      <el-button type="primary" @click="showUploadDialog = true">
        <el-icon><Upload /></el-icon>
        上传 Skill 包
      </el-button>
      <el-button type="success" @click="showGenerateDialog = true">
        <el-icon><MagicStick /></el-icon>
        生成技能
      </el-button>
      <el-select v-model="filterCategory" placeholder="分类筛选" clearable style="width: 160px">
        <el-option v-for="cat in categories" :key="cat" :label="cat" :value="cat" />
      </el-select>
      <el-input
        v-model="searchQuery"
        placeholder="搜索技能"
        style="width: 260px"
        clearable
        :prefix-icon="Search"
      />
    </div>

    <div class="op-grid">
      <el-card v-for="skill in filteredSkills" :key="skill.id" class="skill-card" shadow="hover">
        <template #header>
          <div class="card-header">
            <span class="skill-name">{{ skill.display_name || skill.name }}</span>
            <el-tag size="small" :type="categoryColor(skill.category)">{{ skill.category || '未分类' }}</el-tag>
          </div>
        </template>
        <p class="skill-desc">{{ skill.description || '暂无描述' }}</p>

        <div v-if="skill.skill_md" class="skill-md-preview">
          {{ truncateMarkdown(skill.skill_md) }}
        </div>

        <div class="skill-meta">
          <el-tag v-if="skill.scripts?.length" size="small" effect="plain">
            {{ skill.scripts.length }} 个脚本
          </el-tag>
          <el-tag v-if="skill.version" size="small" effect="plain">v{{ skill.version }}</el-tag>
        </div>

        <div class="skill-actions">
          <el-button size="small" type="primary" @click="openDetail(skill)">
            <el-icon><Edit /></el-icon> 修改
          </el-button>
          <el-button size="small" type="success" plain @click="openRun(skill)">
            <el-icon><VideoPlay /></el-icon> 执行
          </el-button>
          <el-button size="small" @click="downloadSkill(skill)">
            <el-icon><Download /></el-icon> 下载
          </el-button>
          <el-button size="small" type="danger" plain @click="confirmDelete(skill)">
            <el-icon><Delete /></el-icon>
          </el-button>
        </div>
      </el-card>
    </div>

    <el-empty v-if="filteredSkills.length === 0" description="暂无技能，请上传 Skill 包或使用 AI 生成" />

    <!-- ==================== 上传对话框 ==================== -->
    <el-dialog v-model="showUploadDialog" title="上传 Skill 包" width="480px">
      <el-alert type="info" :closable="false" style="margin-bottom:16px">
        <template #title>
          请上传 .zip 格式的 Skill 包，包内需包含 SKILL.md 文件
        </template>
      </el-alert>
      <el-upload
        drag
        :show-file-list="false"
        :before-upload="validateZip"
        :http-request="handleUploadZip"
        accept=".zip"
      >
        <el-icon style="font-size: 48px"><UploadFilled /></el-icon>
        <div class="upload-text">拖拽或点击上传 .zip 文件</div>
      </el-upload>
      <template #footer>
        <el-button @click="showUploadDialog = false">取消</el-button>
      </template>
    </el-dialog>

    <!-- ==================== AI 生成对话框 ==================== -->
    <el-dialog v-model="showGenerateDialog" title="AI 生成技能" width="550px" @closed="generatePrompt = ''">
      <el-alert type="info" :closable="false" style="margin-bottom:16px">
        <template #title>
          Skill Creator 将根据需求描述生成完整 Skill 包（SKILL.md + 脚本）
        </template>
      </el-alert>
      <el-form label-width="80px">
        <el-form-item label="需求描述">
          <el-input
            v-model="generatePrompt"
            type="textarea"
            :rows="5"
            placeholder="用自然语言描述你需要什么技能，例如：按照年代筛选文物数据，支持根据数据源名称查询，返回前100条"
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

    <!-- ==================== 技能详情/修改 Drawer ==================== -->
    <el-drawer
      v-model="detailDrawer"
      :title="detailSkill?.display_name || detailSkill?.name || '技能详情'"
      size="70%"
      destroy-on-close
    >
      <div v-if="detailSkill" class="detail-container">
        <div class="nl-modify-section">
          <div class="nl-modify-header">
            <span class="nl-modify-title">自然语言修改</span>
            <span class="nl-modify-hint">用自然语言描述你想如何修改这个技能</span>
          </div>
          <div class="nl-modify-input-row">
            <el-input
              v-model="modifyInstruction"
              type="textarea"
              :rows="2"
              placeholder="例如：把描述改成更专业的风格，添加使用示例，修改分类为数据处理"
              class="nl-modify-input"
            />
            <el-button
              type="primary"
              @click="handleModifySkill"
              :loading="modifying"
              :disabled="!modifyInstruction.trim()"
            >
              <el-icon><MagicStick /></el-icon>
              AI 修改
            </el-button>
          </div>
          <div v-if="modifyError" class="modify-error">
            <el-alert :title="modifyError" type="error" show-icon :closable="false" />
          </div>
          <div v-if="modifying" class="modify-thinking-box">
            <div class="modify-thinking-header">
              <el-icon class="thinking-spin"><Loading /></el-icon>
              <span class="modify-thinking-title">{{ modifyPhase === 'thinking' ? 'AI 正在思考...' : 'AI 正在生成修改内容...' }}</span>
            </div>
            <div v-if="modifyThinking" class="modify-thinking-content">
              {{ modifyThinking }}
            </div>
            <div v-else class="modify-thinking-placeholder">等待模型响应中</div>
          </div>
        </div>

        <el-divider />

        <div class="detail-preview-label">技能详情预览</div>

        <el-tabs v-model="detailTab" class="detail-tabs">
          <el-tab-pane label="SKILL.md" name="md">
            <div v-if="mdEditContent" class="markdown-body" v-html="renderMarkdown(mdEditContent)"></div>
            <el-empty v-else description="暂无 SKILL.md 内容" />
          </el-tab-pane>

          <el-tab-pane label="脚本列表" name="scripts">
            <div class="scripts-header">
              <span>{{ detailSkill.scripts?.length || 0 }} 个脚本</span>
            </div>
            <div v-if="detailSkill.scripts?.length" class="scripts-list">
              <div
                v-for="script in detailSkill.scripts"
                :key="script.name"
                class="script-item"
              >
                <div class="script-item-header" @click="toggleScript(script.name)">
                  <el-icon><component :is="expandedScript === script.name ? 'CaretBottom' : 'CaretRight'" /></el-icon>
                  <span class="script-name">{{ script.name }}</span>
                  <span class="script-size">{{ script.size ? (script.size / 1024).toFixed(1) + ' KB' : '' }}</span>
                </div>
                <div v-if="expandedScript === script.name" class="script-body">
                  <textarea
                    v-model="scriptContents[script.name]"
                    class="script-editor"
                    spellcheck="false"
                  ></textarea>
                  <div class="script-actions">
                    <el-button size="small" type="primary" @click="saveScriptContent(script.name)" :loading="savingScript">
                      <el-icon><Check /></el-icon> 保存
                    </el-button>
                    <el-button size="small" type="success" @click="openRun(detailSkill, script.name)">
                      <el-icon><VideoPlay /></el-icon> 执行
                    </el-button>
                  </div>
                </div>
              </div>
            </div>
            <el-empty v-else description="暂无脚本" />
          </el-tab-pane>

          <el-tab-pane label="属性" name="props">
            <el-descriptions :column="2" border>
              <el-descriptions-item label="名称">{{ detailSkill.name }}</el-descriptions-item>
              <el-descriptions-item label="显示名">{{ detailSkill.display_name }}</el-descriptions-item>
              <el-descriptions-item label="分类">
                <el-tag size="small" :type="categoryColor(detailSkill.category)">{{ detailSkill.category || '-' }}</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="版本">v{{ detailSkill.version }}</el-descriptions-item>
              <el-descriptions-item label="可见性">{{ detailSkill.visibility }}</el-descriptions-item>
              <el-descriptions-item label="使用次数">{{ detailSkill.usage_count }}</el-descriptions-item>
              <el-descriptions-item label="存储路径" :span="2">
                <code>{{ detailSkill.skill_path }}</code>
              </el-descriptions-item>
              <el-descriptions-item label="描述" :span="2">{{ detailSkill.description || '-' }}</el-descriptions-item>
              <el-descriptions-item label="标签" :span="2">
                <el-tag v-for="tag in (detailSkill.tags || [])" :key="tag" size="small" style="margin-right:4px">{{ tag }}</el-tag>
                <span v-if="!detailSkill.tags?.length">-</span>
              </el-descriptions-item>
              <el-descriptions-item label="创建时间">{{ formatDate(detailSkill.created_at) }}</el-descriptions-item>
              <el-descriptions-item label="更新时间">{{ formatDate(detailSkill.updated_at) }}</el-descriptions-item>
            </el-descriptions>
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-drawer>

    <!-- ==================== 执行技能对话框 ==================== -->
    <el-dialog v-model="execDialog" title="执行技能" width="750px" destroy-on-close @closed="execResult = null">
      <div v-if="execSkill" class="exec-container">
        <div class="exec-info">
          <span class="exec-skill-name">{{ execSkill.display_name || execSkill.name }}</span>
          <el-tag size="small" type="primary">脚本: {{ execScriptName }}</el-tag>
        </div>

        <el-tabs v-model="execTab" style="margin-top:16px">
          <el-tab-pane label="自然语言调用" name="nl">
            <el-alert type="info" :closable="false" style="margin-bottom:12px">
              <template #title>用自然语言描述你想要执行的操作，AI 将自动推断参数并调用技能</template>
            </el-alert>
            <el-form label-width="100px">
              <el-form-item label="数据源">
                <el-select v-model="execDatasourceId" placeholder="选择数据源（可选）" clearable style="width:100%">
                  <el-option
                    v-for="ds in datasources"
                    :key="ds.id"
                    :label="ds.name"
                    :value="ds.id"
                  />
                </el-select>
              </el-form-item>
              <el-form-item label="调用指令">
                <el-input
                  v-model="execNLQuery"
                  type="textarea"
                  :rows="4"
                  placeholder="例如：帮我查询明代的青铜器数据，限制返回50条"
                />
              </el-form-item>
            </el-form>
            <div style="display:flex;justify-content:flex-end;gap:8px;margin-bottom:16px">
              <el-button type="primary" @click="handleRunSkillNL" :loading="execRunning">
                <el-icon><MagicStick /></el-icon> AI 调用
              </el-button>
            </div>
          </el-tab-pane>

          <el-tab-pane label="命令调用" name="cmd">
            <el-alert type="info" :closable="false" style="margin-bottom:12px">
              <template #title>使用 / 命令直接调用技能，格式：/技能名 参数1=值1 参数2=值2</template>
            </el-alert>

            <div v-if="skillParams.length" class="cmd-params-form">
              <div class="cmd-params-title">参数填写（根据技能定义自动生成）</div>
              <el-form label-width="100px" size="small">
                <el-form-item v-for="p in skillParams" :key="p.name" :label="p.display_name || p.name" :required="p.required">
                  <el-select v-if="p.is_datasource" v-model="cmdParamValues[p.name]" placeholder="选择数据源" clearable style="width:100%">
                    <el-option v-for="ds in datasources" :key="ds.id" :label="ds.name" :value="ds.name" />
                  </el-select>
                  <el-select v-else-if="p.is_table" v-model="cmdParamValues[p.name]" placeholder="选择表名" clearable style="width:100%">
                    <el-option v-for="t in tableOptions" :key="t" :label="t" :value="t" />
                  </el-select>
                  <el-input v-else-if="p.type === 'int'" v-model.number="cmdParamValues[p.name]" :placeholder="p.description || p.name" type="number" />
                  <el-switch v-else-if="p.type === 'bool'" v-model="cmdParamValues[p.name]" />
                  <el-input v-else v-model="cmdParamValues[p.name]" :placeholder="p.description || p.name" />
                </el-form-item>
              </el-form>
              <el-button type="primary" size="small" @click="buildCmdFromParams" style="margin-bottom:12px">
                生成命令
              </el-button>
            </div>

            <div v-if="cmdExamples.length" class="cmd-examples">
              <div class="cmd-examples-title">命令示例（点击填入）</div>
              <div class="cmd-example-item" v-for="ex in cmdExamples" :key="ex.cmd" @click="execCmdStr = ex.cmd">
                <code>{{ ex.cmd }}</code>
                <span v-if="ex.desc" class="cmd-example-desc">{{ ex.desc }}</span>
              </div>
            </div>

            <div class="cmd-input-row">
              <el-input
                v-model="execCmdStr"
                type="textarea"
                :rows="3"
                :placeholder="cmdPlaceholder"
                @keydown.enter.ctrl="handleRunCmd"
              />
              <el-button type="primary" @click="handleRunCmd" :loading="execRunning" style="margin-top:8px">
                <el-icon><CaretRight /></el-icon> 执行
              </el-button>
            </div>
            <div v-if="cmdParseHint" class="cmd-parse-hint">
              <el-tag size="small" type="info">{{ cmdParseHint }}</el-tag>
            </div>
          </el-tab-pane>
        </el-tabs>

        <div v-if="execResult" class="exec-result">
          <div class="exec-result-header">
            <el-tag :type="execResult.success ? 'success' : 'danger'">
              {{ execResult.success ? '成功' : '失败' }}
            </el-tag>
            <span v-if="execResult.execution_time_ms" class="exec-time">
              {{ execResult.execution_time_ms }}ms
            </span>
          </div>
          <div v-if="execResult.error" class="exec-error-block">
            <pre>{{ execResult.error }}</pre>
          </div>
          <div v-if="execResult.stdout" class="exec-stdout-block">
            <div class="exec-label">标准输出:</div>
            <pre>{{ execResult.stdout }}</pre>
          </div>
          <div v-if="execResult.result !== undefined && execResult.result !== null" class="exec-result-block">
            <div class="exec-label">返回结果:</div>
            <pre>{{ formatResult(execResult.result) }}</pre>
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import {
  Upload, Download, Delete, VideoPlay, CaretRight, Search, Check,
  MagicStick, Edit, CopyDocument, UploadFilled, CaretBottom, Loading,
} from '@element-plus/icons-vue'
import api from '@/api/index'
import { ElMessage, ElMessageBox } from 'element-plus'
import markdownIt from 'markdown-it'

const skills = ref<any[]>([])
const categories = ref<string[]>([])
const filterCategory = ref('')
const searchQuery = ref('')

const filteredSkills = computed(() => {
  let list = skills.value
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

const datasources = ref<any[]>([])


async function loadSkills() {
  try {
    skills.value = await api.get('/skills')
    categories.value = await api.get('/skills/categories')
  } catch (e: any) {
    ElMessage.error('加载技能失败')
  }
}

async function loadDatasources() {
  try {
    datasources.value = await api.get('/datasources')
  } catch (e: any) {
    /* ignore */
  }
}

function categoryColor(cat: string) {
  const map: Record<string, string> = {
    transform: 'primary',
    aggregate: 'success',
    join: 'warning',
    clean: 'info',
    analysis: 'danger',
    data_processing: '',
    ai_generated: 'success',
  }
  return map[cat] || ''
}

function truncateMarkdown(src: string): string {
  const text = src.replace(/---[\s\S]*?---/, '').replace(/^#+\s+.*$/gm, '').replace(/\*\*/g, '').replace(/`/g, '').trim()
  return text.length > 120 ? text.slice(0, 120) + '...' : text
}

function renderMarkdown(src: string): string {
  return markdownIt().render(src)
}

function formatDate(d: string | null): string {
  if (!d) return '-'
  return new Date(d).toLocaleString()
}

function formatResult(result: any): string {
  try {
    return JSON.stringify(result, null, 2)
  } catch {
    return String(result)
  }
}

// ==================== 上传 ====================
const showUploadDialog = ref(false)

function validateZip(file: any) {
  if (!file.name.toLowerCase().endsWith('.zip')) {
    ElMessage.error('只支持 .zip 格式的 Skill 包')
    return false
  }
  return true
}

async function handleUploadZip(options: any) {
  const formData = new FormData()
  formData.append('file', options.file)
  try {
    const res = await api.post('/skills/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    ElMessage.success(`Skill 包 "${res.display_name || res.name}" 已上传`)
    showUploadDialog.value = false
    await loadSkills()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '上传失败')
  }
}

// ==================== 下载 ====================
function downloadSkill(skill: any) {
  const token = localStorage.getItem('access_token')
  const url = `/api/v1/skills/${skill.id}/download`
  if (token) {
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.blob())
      .then((blob) => {
        const blobUrl = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = blobUrl
        a.download = `${skill.name}.zip`
        a.click()
        URL.revokeObjectURL(blobUrl)
      })
  }
}

// ==================== 删除 ====================
async function confirmDelete(skill: any) {
  try {
    await ElMessageBox.confirm(
      `确定要删除技能 "${skill.display_name || skill.name}" 吗？此操作不可恢复。`,
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    await api.delete(`/skills/${skill.id}`)
    ElMessage.success('删除成功')
    await loadSkills()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e.response?.data?.detail || '删除失败')
    }
  }
}

// ==================== AI 生成 ====================
const showGenerateDialog = ref(false)
const generatePrompt = ref('')
const generating = ref(false)

async function handleGenerate() {
  if (!generatePrompt.value.trim()) {
    ElMessage.warning('请输入需求描述')
    return
  }
  generating.value = true
  try {
    const res = await api.post('/skills/generate', { prompt: generatePrompt.value.trim() }, { timeout: 180000 })
    ElMessage.success(`技能 "${res.display_name || res.name}" 已生成`)
    showGenerateDialog.value = false
    generatePrompt.value = ''
    await loadSkills()
    detailSkill.value = res
    mdEditContent.value = res.skill_md || ''
    modifyInstruction.value = ''
    detailTab.value = 'md'
    detailDrawer.value = true
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '生成失败')
  } finally {
    generating.value = false
  }
}

// ==================== 技能详情/修改 ====================
const detailDrawer = ref(false)
const detailSkill = ref<any>(null)
const detailTab = ref('md')
const mdEditContent = ref('')
const modifyInstruction = ref('')
const modifying = ref(false)
const modifyError = ref('')
const modifyThinking = ref('')
const modifyPhase = ref<'thinking'|'generating'|'idle'>('idle')
const modifyAbortCtrl = ref<AbortController | null>(null)

const expandedScript = ref('')
const scriptContents = reactive<Record<string, string>>({})
const savingScript = ref(false)

function openDetail(skill: any) {
  detailSkill.value = skill
  mdEditContent.value = skill.skill_md || ''
  modifyInstruction.value = ''
  modifyError.value = ''
  modifyPhase.value = 'idle'
  detailTab.value = 'md'

  scriptContents.value = {}
  expandedScript.value = ''
  for (const s of (skill.scripts || [])) {
    scriptContents[s.name] = ''
  }

  detailDrawer.value = true
}

async function handleModifySkill() {
  if (!detailSkill.value || !modifyInstruction.value.trim()) return
  modifying.value = true
  modifyError.value = ''
  modifyThinking.value = ''
  modifyPhase.value = 'thinking'

  const ctrl = new AbortController()
  modifyAbortCtrl.value = ctrl

  try {
    const token = localStorage.getItem('access_token')
    const response = await fetch(`/api/v1/skills/${detailSkill.value.id}/modify-stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ instruction: modifyInstruction.value.trim() }),
      signal: ctrl.signal,
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
            modifyPhase.value = 'generating'
            if (!modifyThinking.value) {
              modifyThinking.value = '正在生成修改内容...'
            }
          } else if (data.type === 'done') {
            if (data.skill) {
              detailSkill.value = data.skill
              mdEditContent.value = data.skill.skill_md || ''
            }
            modifyInstruction.value = ''
            ElMessage.success('技能已通过 AI 修改')
            await loadSkills()
          } else if (data.type === 'error') {
            modifyError.value = data.content || '修改失败'
          } else if (data.type === 'cancelled') {
            ElMessage.info('修改已取消')
          }
        } catch {
          // skip malformed JSON
        }
      }
    }
  } catch (e: any) {
    if (e.name !== 'AbortError') {
      modifyError.value = e.response?.data?.detail || e.message || '修改失败，请检查 LLM 配置'
    }
  } finally {
    modifying.value = false
    modifyPhase.value = 'idle'
    modifyAbortCtrl.value = null
  }
}

async function toggleScript(name: string) {
  if (expandedScript.value === name) {
    expandedScript.value = ''
    return
  }
  expandedScript.value = name
  if (!scriptContents[name]) {
    try {
      const res = await api.get(`/skills/${detailSkill.value.id}/scripts/${name}`)
      scriptContents[name] = res.content || ''
    } catch (e: any) {
      ElMessage.error('加载脚本失败')
    }
  }
}

async function saveScriptContent(name: string) {
  if (!detailSkill.value) return
  savingScript.value = true
  try {
    await api.put(`/skills/${detailSkill.value.id}/scripts/${name}`, {
      content: scriptContents[name],
    })
    ElMessage.success(`脚本 ${name} 已保存`)
    detailSkill.value.scripts = await api.get(`/skills/${detailSkill.value.id}/scripts`)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    savingScript.value = false
  }
}

// ==================== 执行技能 ====================
const execDialog = ref(false)
const execSkill = ref<any>(null)
const execScriptName = ref('main.py')
const execDatasourceId = ref('')
const execTableName = ref('')
const execParamsStr = ref('')
const execRunning = ref(false)
const execResult = ref<any>(null)
const execTab = ref('nl')
const execNLQuery = ref('')
const execCmdStr = ref('')
const skillParams = ref<any[]>([])
const cmdParamValues = reactive<Record<string, any>>({})
const tableOptions = ref<string[]>([])

// 监听数据源选择，自动加载表列表
watch(execDatasourceId, async (newVal) => {
  if (newVal) {
    try {
      const ds = datasources.value.find((d: any) => d.id === newVal)
      if (ds) {
        const tree = await api.get(`/datasources/${newVal}/tree`)
        tableOptions.value = tree.map((t: any) => t.label || t.table_name).filter(Boolean)
      }
    } catch (e) {
      console.error('加载表列表失败', e)
      tableOptions.value = []
    }
  } else {
    tableOptions.value = []
  }
})

const cmdPlaceholder = computed(() => {
  const name = execSkill.value?.name || 'skill'
  if (skillParams.value.length) {
    const paramHint = skillParams.value
      .filter((p: any) => p.required)
      .map((p: any) => `${p.name}=<${p.type}>`)
      .join(' ')
    return `/${name} ${paramHint}`
  }
  return `/${name} 参数1=值1 参数2=值2`
})

const cmdParseHint = computed(() => {
  const cmd = execCmdStr.value.trim()
  if (!cmd || !cmd.startsWith('/')) return ''
  const parts = cmd.split(/\s+/)
  const skillName = parts[0].slice(1)
  const params: Record<string, string> = {}
  for (let i = 1; i < parts.length; i++) {
    const eq = parts[i].indexOf('=')
    if (eq > 0) {
      params[parts[i].slice(0, eq)] = parts[i].slice(eq + 1)
    }
  }
  const paramKeys = Object.keys(params)
  if (paramKeys.length === 0) return `技能: ${skillName}（无参数）`
  return `技能: ${skillName} | ${paramKeys.map(k => `${k}=${params[k]}`).join(', ')}`
})

const cmdExamples = computed(() => {
  const name = execSkill.value?.name || 'skill'
  const params = skillParams.value
  if (!params.length) {
    return [
      { cmd: `/${name} datasource=数据源名 table=表名`, desc: '基本调用' },
      { cmd: `/${name} column=名称 limit=50`, desc: '带参数调用' },
    ]
  }

  const required = params.filter((p: any) => p.required)
  const optional = params.filter((p: any) => !p.required)
  const examples: { cmd: string; desc: string }[] = []

  const requiredPart = required.map((p: any) => {
    const val = p.is_datasource ? '数据源名' : p.is_table ? '表名' : p.example || `值`
    return `${p.name}=${val}`
  }).join(' ')

  examples.push({ cmd: `/${name} ${requiredPart}`, desc: '必填参数调用' })

  if (optional.length > 0) {
    const allPart = [...required, ...optional.slice(0, 2)].map((p: any) => {
      const val = p.is_datasource ? '数据源名' : p.is_table ? '表名' : p.example || p.default || '值'
      return `${p.name}=${val}`
    }).join(' ')
    examples.push({ cmd: `/${name} ${allPart}`, desc: '完整参数调用' })
  }

  return examples
})

async function openRun(skill: any, scriptName?: string) {
  execSkill.value = skill
  execScriptName.value = scriptName || (skill.scripts?.[0]?.name || 'main.py')
  execDatasourceId.value = ''
  execTableName.value = ''
  execParamsStr.value = ''
  execNLQuery.value = ''
  execCmdStr.value = `/${skill.name || 'skill'} `
  execTab.value = 'nl'
  execResult.value = null
  skillParams.value = []
  for (const key of Object.keys(cmdParamValues)) {
    delete cmdParamValues[key]
  }
  execDialog.value = true

  try {
    const params = await api.get(`/skills/${skill.id}/params`)
    skillParams.value = params || []
    for (const p of params) {
      if (p.default !== null && p.default !== undefined) {
        cmdParamValues[p.name] = p.default
      } else if (p.type === 'bool') {
        cmdParamValues[p.name] = false
      } else {
        cmdParamValues[p.name] = ''
      }
    }
  } catch {
    /* ignore */
  }
}

function buildCmdFromParams() {
  const name = execSkill.value?.name || 'skill'
  const parts = [`/${name}`]
  for (const p of skillParams.value) {
    const val = cmdParamValues[p.name]
    if (val === '' || val === null || val === undefined) continue
    if (p.is_datasource) {
      parts.push(`datasource=${val}`)
    } else if (p.is_table) {
      parts.push(`tables=${Array.isArray(val) ? val.join(',') : val}`)
    } else if (p.is_list && Array.isArray(val)) {
      parts.push(`${p.name}=${val.join(',')}`)
    } else {
      parts.push(`${p.name}=${val}`)
    }
  }
  execCmdStr.value = parts.join(' ')
}

async function handleRunSkill() {
  if (!execSkill.value) return
  execRunning.value = true
  execResult.value = null

  let parameters: any = {}
  if (execParamsStr.value.trim()) {
    try {
      parameters = JSON.parse(execParamsStr.value.trim())
    } catch {
      ElMessage.error('参数格式错误，请输入有效的 JSON')
      execRunning.value = false
      return
    }
  }

  try {
    const res = await api.post(
      `/skills/${execSkill.value.id}/run`,
      {
        script_name: execScriptName.value,
        datasource_id: execDatasourceId.value || undefined,
        table_name: execTableName.value || undefined,
        parameters,
      },
      { timeout: 60000 }
    )
    execResult.value = res
  } catch (e: any) {
    execResult.value = {
      success: false,
      error: e.response?.data?.detail || String(e),
    }
  } finally {
    execRunning.value = false
  }
}

async function handleRunSkillNL() {
  if (!execSkill.value) return
  if (!execNLQuery.value.trim()) {
    ElMessage.warning('请输入调用指令')
    return
  }
  execRunning.value = true
  execResult.value = null

  try {
    const res = await api.post(
      `/skills/${execSkill.value.id}/run-nl`,
      {
        query: execNLQuery.value.trim(),
        script_name: execScriptName.value,
        datasource_id: execDatasourceId.value || undefined,
        table_name: execTableName.value || undefined,
      },
      { timeout: 120000 }
    )
    execResult.value = res
  } catch (e: any) {
    execResult.value = {
      success: false,
      error: e.response?.data?.detail || String(e),
    }
  } finally {
    execRunning.value = false
  }
}

async function handleRunCmd() {
  if (!execSkill.value) return
  const cmd = execCmdStr.value.trim()
  if (!cmd) {
    ElMessage.warning('请输入命令')
    return
  }

  let parameters: Record<string, any> = {}
  let datasourceName = ''
  let tableName = ''
  let dsId = execDatasourceId.value

  if (cmd.startsWith('/')) {
    const parts = cmd.split(/\s+/)
    for (let i = 1; i < parts.length; i++) {
      const eq = parts[i].indexOf('=')
      if (eq > 0) {
        const key = parts[i].slice(0, eq)
        const val = parts[i].slice(eq + 1)
        if (key === 'datasource') {
          datasourceName = val
          parameters['datasource'] = val
        } else if (key === 'table' || key === 'tables') {
          tableName = val
          parameters['tables'] = val.split(',')
        } else {
          try {
            parameters[key] = JSON.parse(val)
          } catch {
            parameters[key] = val
          }
        }
      }
    }
  } else {
    ElMessage.error('命令格式错误，请以 / 开头，例如 /filter condition="age>18"')
    return
  }

  if (datasourceName && !dsId) {
    const ds = datasources.value.find((d: any) => d.name === datasourceName)
    if (ds) dsId = ds.id
  }

  execRunning.value = true
  execResult.value = null

  try {
    const res = await api.post(
      `/skills/${execSkill.value.id}/run`,
      {
        script_name: execScriptName.value,
        datasource_id: dsId || undefined,
        table_name: tableName || execTableName.value || undefined,
        parameters,
      },
      { timeout: 60000 }
    )
    execResult.value = res
  } catch (e: any) {
    execResult.value = {
      success: false,
      error: e.response?.data?.detail || String(e),
    }
  } finally {
    execRunning.value = false
  }
}

onMounted(() => {
  loadSkills()
  loadDatasources()
})
</script>

<style lang="scss" scoped>
.skill-page {
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

.skill-card {
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
    .skill-name {
      font-weight: 600;
      font-size: 15px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }
  .skill-desc {
    color: #666;
    font-size: 13px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .skill-md-preview {
    color: #909399;
    font-size: 12px;
    line-height: 1.6;
    margin: 6px 0 0;
    padding: 8px 10px;
    background: #f9fafb;
    border-left: 3px solid #409eff;
    border-radius: 0 4px 4px 0;
    overflow: hidden;
    text-overflow: ellipsis;
    max-height: 48px;
  }
  .skill-meta {
    margin: 8px 0;
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    min-height: 26px;
  }
  .skill-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: auto;
    padding-top: 12px;
  }
}

.upload-text {
  margin-top: 12px;
  color: #909399;
}

// Detail Drawer
.detail-container {
  padding: 0 4px;
}

.detail-preview-label {
  font-size: 13px;
  color: #909399;
  margin-bottom: 8px;
}

.nl-modify-section {
  background: #f5f7fa;
  border-radius: 8px;
  padding: 16px;

  .nl-modify-header {
    display: flex;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 12px;

    .nl-modify-title {
      font-weight: 600;
      font-size: 15px;
      color: #303133;
    }

    .nl-modify-hint {
      font-size: 12px;
      color: #909399;
    }
  }

  .nl-modify-input-row {
    display: flex;
    gap: 12px;
    align-items: flex-start;

    .nl-modify-input {
      flex: 1;
    }

    .el-button {
      flex-shrink: 0;
      margin-top: 0;
    }
  }

  .modify-error {
    margin-top: 10px;
  }

  .modify-thinking-box {
    margin-top: 12px;
    background: #fff;
    border: 1px solid #e4e7ed;
    border-radius: 6px;
    overflow: hidden;

    .modify-thinking-header {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 8px 12px;
      background: #ecf5ff;
      border-bottom: 1px solid #e4e7ed;
      font-size: 13px;
      color: #409eff;

      .thinking-spin {
        animation: rotate 1.2s linear infinite;
      }

      .modify-thinking-title {
        font-weight: 500;
      }
    }

    .modify-thinking-content {
      padding: 10px 12px;
      font-size: 13px;
      color: #606266;
      line-height: 1.6;
      white-space: pre-wrap;
      word-break: break-word;
      max-height: 260px;
      overflow-y: auto;
    }

    .modify-thinking-placeholder {
      padding: 10px 12px;
      font-size: 13px;
      color: #c0c4cc;
    }
  }
}

@keyframes rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.detail-tabs {
  :deep(.el-tabs__header) {
    position: sticky;
    top: 0;
    background: #fff;
    z-index: 10;
  }
}

// Scripts
.scripts-header {
  margin-bottom: 8px;
  color: #909399;
  font-size: 13px;
}

.scripts-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.script-item {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  overflow: hidden;

  .script-item-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    cursor: pointer;
    background: #fafafa;
    &:hover { background: #f0f2f5; }
    .script-name {
      font-family: 'Consolas', monospace;
      font-size: 13px;
      font-weight: 500;
      flex: 1;
    }
    .script-size {
      font-size: 12px;
      color: #909399;
    }
  }

  .script-body {
    padding: 8px 12px 12px;
    border-top: 1px solid #ebeef5;
  }

  .script-editor {
    width: 100%;
    height: 300px;
    font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
    font-size: 13px;
    line-height: 1.5;
    border: 1px solid #dcdfe6;
    border-radius: 6px;
    padding: 12px;
    resize: vertical;
    background: #1e1e1e;
    color: #d4d4d4;
    outline: none;
    &:focus { border-color: #409eff; }
  }

  .script-actions {
    display: flex;
    gap: 8px;
    margin-top: 8px;
  }
}

// Execution
.exec-container {
  .exec-info {
    display: flex;
    align-items: center;
    gap: 12px;
    .exec-skill-name {
      font-weight: 600;
      font-size: 16px;
    }
  }
}

.cmd-input-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.cmd-examples {
  background: #fafafa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 10px 14px;
  margin-bottom: 12px;

  .cmd-examples-title {
    font-size: 12px;
    color: #909399;
    margin-bottom: 8px;
  }

  .cmd-example-item {
    cursor: pointer;
    padding: 4px 8px;
    border-radius: 4px;
    margin-bottom: 4px;
    transition: background 0.2s;
    display: flex;
    align-items: baseline;
    gap: 8px;

    &:hover {
      background: #ecf5ff;
    }

    code {
      font-family: 'Consolas', 'Monaco', monospace;
      font-size: 13px;
      color: #409eff;
      white-space: nowrap;
    }

    .cmd-example-desc {
      font-size: 12px;
      color: #909399;
    }
  }
}

.cmd-params-form {
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 12px 14px;
  margin-bottom: 12px;

  .cmd-params-title {
    font-size: 12px;
    color: #606266;
    font-weight: 600;
    margin-bottom: 8px;
  }
}

.cmd-parse-hint {
  margin-top: 8px;
}

.exec-result {
  .exec-result-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
  }
  .exec-time { font-size: 12px; color: #909399; }
  .exec-label { font-size: 12px; color: #909399; margin-bottom: 4px; }

  .exec-error-block {
    background: #fef0f0;
    border: 1px solid #fde2e2;
    border-radius: 6px;
    padding: 10px;
    pre { margin: 0; font-size: 12px; color: #f56c6c; white-space: pre-wrap; word-break: break-all; }
  }
  .exec-stdout-block {
    background: #f5f7fa;
    border: 1px solid #e4e7ed;
    border-radius: 6px;
    padding: 10px;
    margin-bottom: 8px;
    pre { margin: 0; font-size: 12px; white-space: pre-wrap; }
  }
  .exec-result-block {
    background: #f0f9eb;
    border: 1px solid #e1f3d8;
    border-radius: 6px;
    padding: 10px;
    pre {
      margin: 0; font-size: 12px; white-space: pre-wrap; word-break: break-all;
      max-height: 300px; overflow-y: auto;
    }
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
    background: #1e1e1e; border-radius: 8px; padding: 14px 18px; overflow-x: auto;
    code { background: none; color: #d4d4d4; padding: 0; }
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