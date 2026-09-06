<template>
  <div class="datasource-container">
    <div class="toolbar">
      <div class="toolbar-left">
        <el-button type="primary" @click="openCreateDialog">
          <el-icon><Plus /></el-icon> {{ t('datasource.createDataSource') }}
        </el-button>
      </div>
      <div class="toolbar-right">
        <el-select v-model="typeFilter" :placeholder="t('datasource.typeFilter')" clearable @change="fetchDataSources" style="width: 160px;">
          <el-option
            v-for="c in connectors"
            :key="c.name"
            :label="c.display_name"
            :value="c.name"
          />
        </el-select>
      </div>
    </div>

    <el-table :data="dataSources" stripe>
      <el-table-column prop="name" :label="t('datasource.name')" />
      <el-table-column prop="type" :label="t('datasource.type')" width="120">
        <template #default="{ row }">
          <el-tag :type="getTypeTagType(row.type)">{{ getTypeLabel(row.type) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="is_active" :label="t('datasource.status')" width="80">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'danger'">
            {{ row.is_active ? t('common.active') : t('common.inactive') }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" :label="t('common.createdAt')" width="180">
        <template #default="{ row }">
          {{ formatDate(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column :label="t('common.actions')" width="400">
        <template #default="{ row }">
          <div class="table-actions">
            <el-button v-if="!row.is_virtual" size="small" @click="testConnection(row.id)">{{ t('common.test') }}</el-button>
            <el-button size="small" @click="browseDataSource(row)">{{ t('datasource.browse') }}</el-button>
            <el-button v-if="!row.is_virtual" size="small" type="success" @click="syncMetadata(row)" :loading="row._syncing">{{ t('datasource.syncMetadata') }}</el-button>
            <el-button v-if="!row.is_virtual" size="small" type="warning" @click="editDataSource(row)">{{ t('common.edit') }}</el-button>
            <el-button v-if="!row.is_virtual" size="small" type="danger" @click="deleteDataSource(row.id)">{{ t('common.delete') }}</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="showCreateDialog" :title="editId ? t('datasource.editDataSource') : t('datasource.createDataSource')" width="600px" @closed="resetForm">
      <el-form :model="configForm" label-position="top" ref="formRef">
        <el-form-item :label="t('datasource.name')" required>
          <el-input v-model="configForm.name" :placeholder="t('datasource.nameRequired')" />
        </el-form-item>
        <el-form-item :label="t('datasource.type')" required>
          <el-select v-model="configForm.type" @change="onTypeChange" style="width: 100%;">
            <el-option
              v-for="c in connectors"
              :key="c.name"
              :label="c.display_name"
              :value="c.name"
            />
          </el-select>
        </el-form-item>

        <el-divider content-position="left">{{ t('datasource.connectionConfig') }}</el-divider>

        <el-form-item
          v-for="field in currentConfigTemplate"
          :key="field.name + '-' + field.label"
          :label="field.label"
          :required="field.required"
          v-show="isFieldVisible(field)"
        >
          <el-input v-if="field.type === 'string'" v-model="configValues[field.name]" :placeholder="field.placeholder || ''" />
          <el-input-number v-else-if="field.type === 'number'" v-model="configValues[field.name]" :min="1" :max="65535" style="width: 100%;" />
          <el-input v-else-if="field.type === 'password'" v-model="configValues[field.name]" type="password" show-password :placeholder="editId ? t('datasource.leaveBlankHint') : t('common.placeholder')" />
          <el-switch v-else-if="field.type === 'boolean'" v-model="configValues[field.name]" />
          <el-select v-else-if="field.type === 'select'" v-model="configValues[field.name]" style="width: 100%;">
            <el-option v-for="opt in (field.options || [])" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
          <el-input v-else-if="field.type === 'filepath'" v-model="configValues[field.name]">
            <template #prepend><el-button @click="openFsBrowserForField(field.name, 'file')" :icon="Document" /></template>
          </el-input>
          <el-input v-else-if="field.type === 'folderpath'" v-model="configValues[field.name]">
            <template #prepend><el-button @click="openFsBrowserForField(field.name, 'folder')" :icon="FolderOpened" /></template>
          </el-input>
          <div v-else-if="field.type === 'filepath_list'" style="width: 100%;">
            <div v-for="(p, i) in (configValues[field.name] || [])" :key="i" class="multi-file-row">
              <el-input v-model="configValues[field.name][i]" :placeholder="t('datasource.filePath')">
                <template #prepend><el-button @click="openFsBrowserForField(field.name, 'file', i)" :icon="Document" /></template>
              </el-input>
              <el-button text type="danger" :icon="Delete" @click="configValues[field.name].splice(i, 1)" />
            </div>
            <el-button size="small" type="primary" plain @click="ensureList(field.name); configValues[field.name].push('')">{{ t('datasource.addFile') }}</el-button>
          </div>
          <el-input v-else v-model="configValues[field.name]" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="editId ? updateDataSource() : createDataSource()" :loading="saving">{{ editId ? t('common.save') : t('common.create') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showBrowseDialog" :title="t('datasource.browseTitle', { name: browsingSource?.name || '' })" width="96%" top="1vh" @opened="onBrowseOpened">
      <div class="browse-layout">
        <div class="browse-sidebar">
          <div class="browse-sidebar-title">
            <span>{{ t('datasource.tables') }}</span>
            <el-button size="small" text :loading="browseLoading" @click="refreshCurrentTable">
              <el-icon><Refresh /></el-icon>
            </el-button>
          </div>
          <el-tooltip
            v-for="item in browseTree"
            :key="item.id"
            :content="item.label"
            placement="right"
            :show-after="300"
          >
            <div
              class="browse-table-item"
              :class="{ active: selectedTable === item.label }"
              @click="selectBrowseTable(item.label)"
            >
              <el-icon style="margin-right: 6px; flex-shrink: 0;"><Grid /></el-icon>
              <span class="browse-table-label">{{ item.label }}</span>
              <span v-if="item.metadata?.data_updated_at" class="browse-table-time">{{ formatUpdateTime(item.metadata.data_updated_at) }}</span>
            </div>
          </el-tooltip>
          <el-empty v-if="browseTree.length === 0 && !browseLoading" :description="isFileSource ? t('datasource.seeRightSide') : t('datasource.noTables')" :image-size="60" />
        </div>
        <div class="browse-content">
          <div v-if="selectedTable && !isFileSource" class="browse-content-header">
            <el-tooltip :content="selectedTable" placement="top" :show-after="300">
              <span class="browse-table-name">{{ selectedTable }}</span>
            </el-tooltip>
            <span class="browse-row-count">{{ t('datasource.totalRowsShowing', { total: browseTotal, shown: browseRows.length }) }}</span>
          </div>
          <div v-if="isFileSource && browseTree.length > 0" class="browse-content-header">
            <span class="browse-table-name">{{ t('datasource.fileList') }}</span>
            <span class="browse-row-count">{{ t('datasource.totalFiles', { count: browseTotal }) }}</span>
          </div>
          <el-table v-if="(selectedTable || isFileSource) && browseRows.length > 0" :data="browseRows" stripe border max-height="80vh" style="width: 100%;">
            <el-table-column
              v-for="col in browseColumns"
              :key="col.name"
              :prop="col.name"
              :label="col.name"
              :min-width="120"
              show-overflow-tooltip
            />
          </el-table>
          <div v-if="!selectedTable && !isFileSource && !browseLoading" class="browse-placeholder">
            <el-empty :description="t('datasource.selectTableHint')" :image-size="80" />
          </div>
          <div v-if="browseLoading" class="browse-placeholder">
            <el-icon class="is-loading" :size="32"><Loading /></el-icon>
          </div>
        </div>
      </div>
    </el-dialog>

    <el-dialog v-model="showConnectorManager" :title="t('datasource.connectorManagement')" width="720px">
      <div style="margin-bottom: 12px;">
        <el-button type="primary" size="small" @click="openConnectorCreate">
          <el-icon><Plus /></el-icon> {{ t('datasource.createConnector') }}
        </el-button>
      </div>
      <el-table :data="connectorList" stripe size="small">
        <el-table-column prop="display_name" :label="t('datasource.name')" width="160" />
        <el-table-column prop="name" :label="t('datasource.identifier')" width="140" />
        <el-table-column prop="description" :label="t('common.description')" show-overflow-tooltip />
        <el-table-column :label="t('datasource.type')" width="80">
          <template #default="{ row }">
            <el-tag :type="row.is_seed ? 'success' : 'info'" size="small">{{ row.is_seed ? t('datasource.seedConnector') : t('datasource.customConnector') }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="160">
          <template #default="{ row }">
            <el-button size="small" @click="openConnectorEdit(row)" :disabled="!row.can_edit">{{ t('common.edit') }}</el-button>
            <el-button size="small" type="danger" @click="deleteConnector(row)" :disabled="!row.can_edit">{{ t('common.delete') }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="showConnectorEditDialog" :title="connectorEditForm.id ? t('datasource.editConnector') : t('datasource.createConnector')" width="680px">
      <el-form label-position="top">
        <el-form-item :label="t('datasource.identifier')" required>
          <el-input v-model="connectorEditForm.name" :disabled="!!connectorEditForm.id" :placeholder="t('datasource.identifierPlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('datasource.displayName')">
          <el-input v-model="connectorEditForm.display_name" />
        </el-form-item>
        <el-form-item :label="t('common.description')">
          <el-input v-model="connectorEditForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item :label="t('datasource.connectorCode')" required>
          <el-input v-model="connectorEditForm.code" type="textarea" :rows="12" :placeholder="t('datasource.connectorCodePlaceholder')" style="font-family: monospace; font-size: 12px;" />
        </el-form-item>
        <el-form-item :label="t('datasource.configTemplate')">
          <el-input v-model="connectorEditForm.config_template" type="textarea" :rows="6" :placeholder="t('datasource.configTemplatePlaceholder')" style="font-family: monospace; font-size: 12px;" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showConnectorEditDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="connectorSaving" @click="saveConnector">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <FileSystemBrowser
      v-model="showFsBrowser"
      :mode="fsBrowserMode"
      :ext="fsBrowserExt"
      :default-path="fsBrowserDefaultPath"
      @select="onFsSelect"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive, computed, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import api from '@/api/index'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document, FolderOpened, Refresh, Setting, Delete, Grid } from '@element-plus/icons-vue'
import FileSystemBrowser from '@/components/FileSystemBrowser.vue'
import { formatTime } from '@/utils/time'

const { t } = useI18n()

const dataSources = ref<any[]>([])
const showCreateDialog = ref(false)
const showBrowseDialog = ref(false)
const browsingSource = ref<any>(null)
const browseTree = ref<any[]>([])
const browseColumns = ref<any[]>([])
const browseRows = ref<any[]>([])
const browseTotal = ref(0)
const selectedTable = ref('')
const browseLoading = ref(false)
const isFileSource = computed(() => browsingSource.value?.type === 'generic_file')
const typeFilter = ref('')
const connectors = ref<any[]>([])
const editId = ref<string | null>(null)
const saving = ref(false)
const showFsBrowser = ref(false)
const fsBrowserMode = ref<'file' | 'folder'>('file')
const fsBrowserExt = ref('')
const fsBrowserDefaultPath = ref('D:/')
const fsBrowserField = ref('')
const fsBrowserTargetIndex = ref(-1)

const configForm = reactive({
  name: '',
  type: '',
})
const configValues = reactive<Record<string, any>>({})

// 连接器类型管理
const showConnectorManager = ref(false)
const connectorList = ref<any[]>([])
const showConnectorEditDialog = ref(false)
const connectorSaving = ref(false)
const connectorEditForm = reactive({
  id: '',
  name: '',
  display_name: '',
  description: '',
  code: '',
  config_template: '',
})

const currentConfigTemplate = computed(() => {
  const c = connectors.value.find(c => c.name === configForm.type)
  return c?.config_template || []
})

const route = useRoute()

onMounted(async () => {
  await fetchConnectors()
  await fetchDataSources()

  const dsId = route.query.ds as string
  const tableName = route.query.table as string
  if (dsId) {
    const source = dataSources.value.find((s: any) => s.id === dsId)
    if (source) {
      await browseDataSource(source)
      if (tableName) {
        await nextTick()
        await selectBrowseTable(tableName)
      }
    }
  }
})

async function fetchConnectors() {
  try {
    connectors.value = await api.get('/connectors/custom')
  } catch {}
}

function getTypeLabel(type: string): string {
  const c = connectors.value.find(c => c.name === type)
  return c?.display_name || type
}

const TAG_PALETTE = ['', 'success', 'warning', 'danger', 'info']
function getTypeTagType(type: string): string {
  const idx = connectors.value.findIndex(c => c.name === type)
  return idx >= 0 ? TAG_PALETTE[idx % TAG_PALETTE.length] : ''
}

function isFieldVisible(field: any): boolean {
  if (!field.depends_on) return true
  for (const [k, v] of Object.entries(field.depends_on)) {
    const cur = configValues[k]
    if (Array.isArray(v)) {
      if (!v.includes(cur)) return false
    } else if (cur !== v) {
      return false
    }
  }
  return true
}

function ensureList(fieldName: string) {
  if (!Array.isArray(configValues[fieldName])) {
    configValues[fieldName] = []
  }
}

function applyTemplateDefaults() {
  Object.keys(configValues).forEach(k => delete configValues[k])
  for (const field of currentConfigTemplate.value) {
    if (field.type === 'filepath_list') {
      configValues[field.name] = field.default ? [...field.default] : []
    } else if (field.type === 'boolean') {
      configValues[field.name] = field.default !== undefined ? field.default : false
    } else {
      configValues[field.name] = field.default !== undefined ? field.default : ''
    }
  }
}

function formatDate(dateStr: string): string {
  if (!dateStr) return '-'
  const d = new Date(dateStr)
  return d.toLocaleString('zh-CN')
}

function formatSize(bytes: number): string {
  if (!bytes || bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

function extractError(e: any): string {
  if (e?.response?.data?.detail) {
    const detail = e.response.data.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map((d: any) => d.msg || String(d)).join('; ')
  }
  return e?.message || t('common.operationFailed')
}

function onTypeChange() {
  applyTemplateDefaults()
}

function resetForm() {
  editId.value = null
  configForm.name = ''
  configForm.type = ''
  Object.keys(configValues).forEach(k => delete configValues[k])
}

function openCreateDialog() {
  editId.value = null
  resetForm()
  configForm.type = connectors.value[0]?.name || ''
  onTypeChange()
  showCreateDialog.value = true
}

function editDataSource(source: any) {
  editId.value = source.id
  configForm.name = source.name
  configForm.type = source.type
  const cfg = source.connection_config || {}
  Object.keys(configValues).forEach(k => delete configValues[k])
  for (const field of currentConfigTemplate.value) {
    const val = cfg[field.name]
    if (field.type === 'filepath_list') {
      configValues[field.name] = Array.isArray(val) ? [...val] : []
    } else if (field.type === 'boolean') {
      configValues[field.name] = val !== undefined ? val : (field.default !== undefined ? field.default : false)
    } else {
      configValues[field.name] = val !== undefined ? val : (field.default !== undefined ? field.default : '')
    }
  }
  showCreateDialog.value = true
}

function buildConnectionConfig(): Record<string, any> {
  const cfg: Record<string, any> = {}
  for (const field of currentConfigTemplate.value) {
    if (!isFieldVisible(field)) continue
    const val = configValues[field.name]
    if (val === '***') continue // 未修改的敏感字段，后端保留旧值
    if (field.type === 'filepath_list') {
      cfg[field.name] = Array.isArray(val) ? val.filter((p: string) => p) : []
      continue
    }
    if (field.type === 'boolean') {
      cfg[field.name] = !!val
      continue
    }
    if (val === '' || val === null || val === undefined) continue
    cfg[field.name] = val
  }
  return cfg
}

async function fetchDataSources() {
  try {
    const params: Record<string, any> = {}
    if (typeFilter.value) {
      params.type = typeFilter.value
    }
    dataSources.value = await api.get('/datasources', { params })
  } catch (e: any) {
    ElMessage.error(extractError(e))
  }
}

async function createDataSource() {
  if (!configForm.name.trim()) {
    ElMessage.warning(t('datasource.nameRequired'))
    return
  }
  saving.value = true
  try {
    const connectionConfig = buildConnectionConfig()
    await api.post('/datasources', {
      name: configForm.name,
      type: configForm.type,
      connection_config: connectionConfig,
    })
    ElMessage.success(t('common.createSuccess'))
    showCreateDialog.value = false
    await fetchDataSources()
  } catch (e: any) {
    ElMessage.error(extractError(e))
  } finally {
    saving.value = false
  }
}

async function updateDataSource() {
  if (!configForm.name.trim()) {
    ElMessage.warning(t('datasource.nameRequired'))
    return
  }
  if (!editId.value) return
  saving.value = true
  try {
    const connectionConfig = buildConnectionConfig()
    await api.put(`/datasources/${editId.value}`, {
      name: configForm.name,
      connection_config: connectionConfig,
    })
    ElMessage.success(t('common.saveSuccess'))
    showCreateDialog.value = false
    await fetchDataSources()
  } catch (e: any) {
    ElMessage.error(extractError(e))
  } finally {
    saving.value = false
  }
}

async function testConnection(id: string) {
  try {
    const res = await api.post(`/datasources/${id}/test`)
    if (res.success) {
      ElMessage.success(res.message || t('datasource.connectionTestSuccess'))
    } else {
      ElMessage.warning(res.message || t('datasource.connectionTestFailed'))
    }
  } catch (e: any) {
    ElMessage.error(extractError(e))
  }
}

async function browseDataSource(source: any) {
  browsingSource.value = source
  browseTree.value = []
  browseRows.value = []
  browseColumns.value = []
  selectedTable.value = ''
  showBrowseDialog.value = true
}

async function onBrowseOpened() {
  if (!browsingSource.value) return
  browseLoading.value = true
  try {
    const tree = await api.get(`/datasources/${browsingSource.value.id}/tree`)
    browseTree.value = isFileSource.value ? [] : (tree || [])
    if (!isFileSource.value && tree && tree.length > 0) {
      selectBrowseTable(tree[0].label)
    } else if (isFileSource.value) {
      // 文件源：直接拉文件列表数据（不依赖选中项）
      const data = await api.get(`/datasources/${browsingSource.value.id}/tables/_/data`, {
        params: { page: 1, page_size: 20 },
      })
      browseColumns.value = data.columns || []
      browseRows.value = data.rows || []
      browseTotal.value = data.total || 0
    }
  } catch (e: any) {
    ElMessage.error(extractError(e))
  } finally {
    browseLoading.value = false
  }
}

async function selectBrowseTable(tableName: string) {
  if (!browsingSource.value) return
  selectedTable.value = tableName
  browseLoading.value = true
  try {
    const data = await api.get(`/datasources/${browsingSource.value.id}/tables/${tableName}/data`, {
      params: { page: 1, page_size: 20 },
    })
    browseColumns.value = data.columns || []
    browseRows.value = data.rows || []
    browseTotal.value = data.total || 0
  } catch (e: any) {
    ElMessage.error(extractError(e))
    browseRows.value = []
    browseColumns.value = []
  } finally {
    browseLoading.value = false
  }
}

function formatUpdateTime(ts: string): string {
  return formatTime(ts)
}

async function refreshCurrentTable() {
  if (selectedTable.value) {
    // 同时刷新树（更新时间）和表数据
    try {
      const tree = await api.get(`/datasources/${browsingSource.value.id}/tree`)
      browseTree.value = tree || []
    } catch { /* ignore */ }
    await selectBrowseTable(selectedTable.value)
  } else {
    await onBrowseOpened()
  }
}

async function deleteDataSource(id: string) {
  try {
    await ElMessageBox.confirm(t('datasource.deleteConfirm'), t('common.deleteConfirm'), { type: 'warning' })
    await api.delete(`/datasources/${id}`)
    ElMessage.success(t('common.deleteSuccess'))
    await fetchDataSources()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(extractError(e))
    }
  }
}

async function syncMetadata(row: any) {
  row._syncing = true
  try {
    const res = await api.post(`/metadata/datasources/${row.id}/sync`, {}, { timeout: 120000 })
    ElMessage.success(t('datasource.syncComplete', { count: res.synced }) + (res.deleted_stale ? t('datasource.cleanStaleTables', { count: res.deleted_stale }) : ''))
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || t('datasource.syncFailed'))
  } finally {
    row._syncing = false
  }
}

function openFsBrowserForField(fieldName: string, mode: 'file' | 'folder', index = -1) {
  fsBrowserField.value = fieldName
  fsBrowserMode.value = mode
  fsBrowserTargetIndex.value = index
  const cur = configValues[fieldName]
  fsBrowserDefaultPath.value = (typeof cur === 'string' ? cur : (Array.isArray(cur) && cur[index] ? cur[index] : '')) || 'D:/'
  showFsBrowser.value = true
}

function onFsSelect(path: string) {
  if (fsBrowserTargetIndex.value >= 0) {
    ensureList(fsBrowserField.value)
    configValues[fsBrowserField.value][fsBrowserTargetIndex.value] = path
  } else {
    configValues[fsBrowserField.value] = path
  }
}

// ========== 连接器类型管理 ==========
async function openConnectorManager() {
  showConnectorManager.value = true
  try {
    connectorList.value = await api.get('/connectors/custom')
  } catch (e: any) {
    ElMessage.error(extractError(e))
  }
}

function openConnectorCreate() {
  connectorEditForm.id = ''
  connectorEditForm.name = ''
  connectorEditForm.display_name = ''
  connectorEditForm.description = ''
  connectorEditForm.code = ''
  connectorEditForm.config_template = ''
  showConnectorEditDialog.value = true
}

function openConnectorEdit(c: any) {
  connectorEditForm.id = c.id
  connectorEditForm.name = c.name
  connectorEditForm.display_name = c.display_name
  connectorEditForm.description = c.description
  connectorEditForm.code = c.code || ''
  connectorEditForm.config_template = c.config_template ? JSON.stringify(c.config_template, null, 2) : ''
  showConnectorEditDialog.value = true
}

async function saveConnector() {
  if (!connectorEditForm.name.trim() || !connectorEditForm.code.trim()) {
    ElMessage.warning(t('datasource.identifierAndCodeRequired'))
    return
  }
  connectorSaving.value = true
  try {
    let config_template: any = []
    if (connectorEditForm.config_template.trim()) {
      config_template = JSON.parse(connectorEditForm.config_template)
    }
    const payload = {
      display_name: connectorEditForm.display_name || connectorEditForm.name,
      description: connectorEditForm.description,
      code: connectorEditForm.code,
      config_template,
    }
    if (connectorEditForm.id) {
      await api.put(`/connectors/custom/${connectorEditForm.id}`, payload)
    } else {
      await api.post('/connectors/custom', { name: connectorEditForm.name.trim().toLowerCase(), ...payload })
    }
    ElMessage.success(t('common.saveSuccess'))
    showConnectorEditDialog.value = false
    connectorList.value = await api.get('/connectors/custom')
    await fetchConnectors()
  } catch (e: any) {
    ElMessage.error(extractError(e))
  } finally {
    connectorSaving.value = false
  }
}

async function deleteConnector(c: any) {
  try {
    await ElMessageBox.confirm(t('datasource.deleteConnectorConfirm', { name: c.display_name }), t('common.deleteConfirm'), { type: 'warning' })
    await api.delete(`/connectors/custom/${c.id}`)
    ElMessage.success(t('common.deleteSuccess'))
    connectorList.value = await api.get('/connectors/custom')
    await fetchConnectors()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(extractError(e))
  }
}
</script>

<style lang="scss" scoped>
.datasource-container {
  padding: 20px;
  background: #fff;
  border-radius: 8px;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
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

.browse-layout {
  display: flex;
  gap: 12px;
  min-height: 82vh;
}

.browse-sidebar {
  width: 220px;
  flex-shrink: 0;
  border: 1px solid #e6e6e6;
  border-radius: 6px;
  overflow-y: auto;
  max-height: 84vh;
}

.browse-sidebar-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  font-weight: 600;
  font-size: 13px;
  color: #303133;
  border-bottom: 1px solid #ebeef5;
  background: #fafafa;
}

.browse-table-item {
  padding: 8px 12px;
  cursor: pointer;
  font-size: 13px;
  color: #606266;
  display: flex;
  align-items: center;
  border-bottom: 1px solid #f5f5f5;
  transition: background 0.15s;
  overflow: hidden;

  .browse-table-label {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .browse-table-time {
    margin-left: auto;
    flex-shrink: 0;
    font-size: 11px;
    color: #909399;
  }

  &:hover {
    background: #f5f7fa;
  }

  &.active {
    background: #ecf5ff;
    color: #409eff;
    font-weight: 500;
  }
}

.browse-content {
  flex: 1;
  min-width: 0;
}

.browse-content-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.browse-table-name {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 60%;
  cursor: default;
}

.table-info-box {
  .table-info-name {
    font-weight: 600;
    font-size: 13px;
    color: #303133;
    word-break: break-all;
    line-height: 1.6;
  }
  .table-info-meta {
    font-size: 12px;
    color: #909399;
    margin-top: 4px;
  }
}

.browse-row-count {
  font-size: 12px;
  color: #909399;
}

.browse-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 70vh;
}

.table-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
.multi-file-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
  width: 100%;
}
</style>
