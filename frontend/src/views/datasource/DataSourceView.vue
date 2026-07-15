<template>
  <div class="datasource-container">
    <div class="toolbar">
      <div class="toolbar-left">
        <el-button type="primary" @click="openCreateDialog">
          <el-icon><Plus /></el-icon> 新建数据源
        </el-button>
      </div>
      <div class="toolbar-right">
        <el-select v-model="typeFilter" placeholder="类型筛选" clearable @change="fetchDataSources" style="width: 160px;">
          <el-option
            v-for="c in connectors"
            :key="c.name"
            :label="c.display_name"
            :value="c.name"
          />
        </el-select>
        <el-button :icon="Setting" @click="openConnectorManager">连接器管理</el-button>
      </div>
    </div>

    <el-table :data="dataSources" stripe>
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="type" label="类型" width="120">
        <template #default="{ row }">
          <el-tag :type="getTypeTagType(row.type)">{{ getTypeLabel(row.type) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="is_active" label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'danger'">
            {{ row.is_active ? '活跃' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="180">
        <template #default="{ row }">
          {{ formatDate(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="400">
        <template #default="{ row }">
          <div class="table-actions">
            <el-button size="small" @click="testConnection(row.id)">测试</el-button>
            <el-button size="small" @click="browseDataSource(row)">浏览</el-button>
            <el-button size="small" type="success" @click="syncMetadata(row)" :loading="row._syncing">同步元数据</el-button>
            <el-button size="small" type="warning" @click="editDataSource(row)">修改</el-button>
            <el-button size="small" type="danger" @click="deleteDataSource(row.id)">删除</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="showCreateDialog" :title="editId ? '编辑数据源' : '新建数据源'" width="600px" @closed="resetForm">
      <el-form :model="configForm" label-width="auto" ref="formRef">
        <el-form-item label="名称" required>
          <el-input v-model="configForm.name" placeholder="请输入数据源名称" />
        </el-form-item>
        <el-form-item label="类型" required>
          <el-select v-model="configForm.type" @change="onTypeChange" style="width: 100%;">
            <el-option
              v-for="c in connectors"
              :key="c.name"
              :label="c.display_name"
              :value="c.name"
            />
          </el-select>
        </el-form-item>

        <el-divider content-position="left">连接配置</el-divider>

        <el-form-item
          v-for="field in currentConfigTemplate"
          :key="field.name + '-' + field.label"
          :label="field.label"
          :required="field.required"
          v-show="isFieldVisible(field)"
        >
          <el-input v-if="field.type === 'string'" v-model="configValues[field.name]" :placeholder="field.placeholder || ''" />
          <el-input-number v-else-if="field.type === 'number'" v-model="configValues[field.name]" :min="1" :max="65535" style="width: 100%;" />
          <el-input v-else-if="field.type === 'password'" v-model="configValues[field.name]" type="password" show-password :placeholder="editId ? '留空则不修改' : '请输入'" />
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
              <el-input v-model="configValues[field.name][i]" placeholder="文件路径">
                <template #prepend><el-button @click="openFsBrowserForField(field.name, 'file', i)" :icon="Document" /></template>
              </el-input>
              <el-button text type="danger" :icon="Delete" @click="configValues[field.name].splice(i, 1)" />
            </div>
            <el-button size="small" type="primary" plain @click="ensureList(field.name); configValues[field.name].push('')">+ 添加文件</el-button>
          </div>
          <el-input v-else v-model="configValues[field.name]" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="editId ? updateDataSource() : createDataSource()" :loading="saving">{{ editId ? '保存' : '创建' }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showBrowseDialog" :title="`浏览: ${browsingSource?.name || ''}`" width="95%" top="2vh" @opened="onBrowseOpened">
      <div class="browse-layout">
        <div class="browse-sidebar">
          <div class="browse-sidebar-title">
            <span>数据表</span>
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
            </div>
          </el-tooltip>
          <el-empty v-if="browseTree.length === 0 && !browseLoading" description="暂无数据表" :image-size="60" />
        </div>
        <div class="browse-content">
          <div v-if="selectedTable" class="browse-content-header">
            <el-tooltip :content="selectedTable" placement="top" :show-after="300">
              <span class="browse-table-name">{{ selectedTable }}</span>
            </el-tooltip>
            <span class="browse-row-count">共 {{ browseTotal }} 条，显示前 {{ browseRows.length }} 行</span>
          </div>
          <el-table v-if="selectedTable" :data="browseRows" stripe border max-height="74vh" style="width: 100%;">
            <el-table-column
              v-for="col in browseColumns"
              :key="col.name"
              :prop="col.name"
              :label="col.name"
              :min-width="120"
              show-overflow-tooltip
            />
          </el-table>
          <div v-if="!selectedTable && !browseLoading" class="browse-placeholder">
            <el-empty description="请从左侧选择一张数据表" :image-size="80" />
          </div>
          <div v-if="browseLoading" class="browse-placeholder">
            <el-icon class="is-loading" :size="32"><Loading /></el-icon>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="showBrowseDialog = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showConnectorManager" title="连接器管理" width="720px">
      <div style="margin-bottom: 12px;">
        <el-button type="primary" size="small" @click="openConnectorCreate">
          <el-icon><Plus /></el-icon> 新建连接器
        </el-button>
      </div>
      <el-table :data="connectorList" stripe size="small">
        <el-table-column prop="display_name" label="名称" width="160" />
        <el-table-column prop="name" label="标识" width="140" />
        <el-table-column prop="description" label="描述" show-overflow-tooltip />
        <el-table-column label="共享" width="80">
          <template #default="{ row }">
            <el-tag :type="row.is_public ? 'success' : 'info'" size="small">{{ row.is_public ? '公开' : '私有' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button size="small" @click="openConnectorEdit(row)" :disabled="!row.can_edit">编辑</el-button>
            <el-button size="small" type="danger" @click="deleteConnector(row)" :disabled="!row.can_edit">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="showConnectorEditDialog" :title="connectorEditForm.id ? '编辑连接器' : '新建连接器'" width="680px">
      <el-form label-width="100px">
        <el-form-item label="标识" required>
          <el-input v-model="connectorEditForm.name" :disabled="!!connectorEditForm.id" placeholder="英文小写，如 mongodb" />
        </el-form-item>
        <el-form-item label="显示名称">
          <el-input v-model="connectorEditForm.display_name" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="connectorEditForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="连接器代码" required>
          <el-input v-model="connectorEditForm.code" type="textarea" :rows="12" placeholder="继承 BaseConnector 的 Python 类代码" style="font-family: monospace; font-size: 12px;" />
        </el-form-item>
        <el-form-item label="配置模板">
          <el-input v-model="connectorEditForm.config_template" type="textarea" :rows="6" placeholder='JSON 数组，如 [{"name":"host","label":"主机","type":"string","required":true}]' style="font-family: monospace; font-size: 12px;" />
        </el-form-item>
        <el-form-item label="公开共享">
          <el-switch v-model="connectorEditForm.is_public" />
          <span style="margin-left: 8px; color: #909399; font-size: 12px;">开启后所有用户可见可用</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showConnectorEditDialog = false">取消</el-button>
        <el-button type="primary" :loading="connectorSaving" @click="saveConnector">保存</el-button>
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
import { ref, onMounted, reactive, computed } from 'vue'
import api from '@/api/index'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document, FolderOpened, Refresh, Setting, Delete } from '@element-plus/icons-vue'
import FileSystemBrowser from '@/components/FileSystemBrowser.vue'

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
  is_public: false,
})

const currentConfigTemplate = computed(() => {
  const c = connectors.value.find(c => c.name === configForm.type)
  return c?.config_template || []
})

onMounted(async () => {
  await fetchConnectors()
  await fetchDataSources()
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
  return e?.message || '操作失败'
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
    ElMessage.warning('请输入数据源名称')
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
    ElMessage.success('创建成功')
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
    ElMessage.warning('请输入数据源名称')
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
    ElMessage.success('保存成功')
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
      ElMessage.success(res.message || '连接测试成功')
    } else {
      ElMessage.warning(res.message || '连接测试失败')
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
    browseTree.value = tree || []
    if (tree && tree.length > 0) {
      selectBrowseTable(tree[0].label)
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

async function refreshCurrentTable() {
  if (selectedTable.value) {
    await selectBrowseTable(selectedTable.value)
  } else {
    await onBrowseOpened()
  }
}

async function deleteDataSource(id: string) {
  try {
    await ElMessageBox.confirm('确定要删除此数据源吗？删除后不可恢复。', '确认删除', { type: 'warning' })
    await api.delete(`/datasources/${id}`)
    ElMessage.success('删除成功')
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
    ElMessage.success(`元数据同步完成: ${res.synced} 张表${res.deleted_stale ? `，清理 ${res.deleted_stale} 张过期表` : ''}`)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '同步失败')
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
  connectorEditForm.is_public = false
  showConnectorEditDialog.value = true
}

function openConnectorEdit(c: any) {
  connectorEditForm.id = c.id
  connectorEditForm.name = c.name
  connectorEditForm.display_name = c.display_name
  connectorEditForm.description = c.description
  connectorEditForm.code = c.code || ''
  connectorEditForm.config_template = c.config_template ? JSON.stringify(c.config_template, null, 2) : ''
  connectorEditForm.is_public = !!c.is_public
  showConnectorEditDialog.value = true
}

async function saveConnector() {
  if (!connectorEditForm.name.trim() || !connectorEditForm.code.trim()) {
    ElMessage.warning('标识和代码必填')
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
      is_public: connectorEditForm.is_public,
    }
    if (connectorEditForm.id) {
      await api.put(`/connectors/custom/${connectorEditForm.id}`, payload)
    } else {
      await api.post('/connectors/custom', { name: connectorEditForm.name.trim().toLowerCase(), ...payload })
    }
    ElMessage.success('保存成功')
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
    await ElMessageBox.confirm(`确定删除连接器「${c.display_name}」吗？已被数据源使用的连接器无法删除。`, '确认删除', { type: 'warning' })
    await api.delete(`/connectors/custom/${c.id}`)
    ElMessage.success('删除成功')
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
  min-height: 74vh;
}

.browse-sidebar {
  width: 220px;
  flex-shrink: 0;
  border: 1px solid #e6e6e6;
  border-radius: 6px;
  overflow-y: auto;
  max-height: 76vh;
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
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
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
