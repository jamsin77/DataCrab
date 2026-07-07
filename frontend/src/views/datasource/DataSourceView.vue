<template>
  <div class="datasource-container">
    <div class="toolbar">
      <div class="toolbar-left">
        <el-button type="primary" @click="openCreateDialog">
          <el-icon><Plus /></el-icon> 新建数据源
        </el-button>
      </div>
      <div class="toolbar-right">
        <el-select v-model="typeFilter" placeholder="类型筛选" clearable @change="fetchDataSources" style="width: 140px;">
          <el-option label="PostgreSQL" value="postgresql" />
          <el-option label="MySQL" value="mysql" />
          <el-option label="CSV" value="csv" />
          <el-option label="Excel" value="excel" />
          <el-option label="ChromaDB 向量库" value="chroma" />
          <el-option label="OBS" value="obs" />
          <el-option label="Hadoop" value="hadoop" />
        </el-select>
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

    <el-dialog v-model="showCreateDialog" :title="editId ? '编辑数据源' : '新建数据源'" width="560px" @closed="resetForm">
      <el-form :model="configForm" label-width="90px" ref="formRef">
        <el-form-item label="名称" required>
          <el-input v-model="configForm.name" placeholder="请输入数据源名称" />
        </el-form-item>
        <el-form-item label="类型" required>
          <el-select v-model="configForm.type" @change="onTypeChange" style="width: 100%;">
            <el-option label="PostgreSQL" value="postgresql" />
            <el-option label="MySQL" value="mysql" />
            <el-option label="CSV 文件" value="csv" />
            <el-option label="Excel 文件" value="excel" />
            <el-option label="ChromaDB 向量库" value="chroma" />
            <el-option label="OBS 华为云对象存储" value="obs" />
            <el-option label="Hadoop HDFS" value="hadoop" />
          </el-select>
        </el-form-item>

        <el-divider content-position="left">连接配置</el-divider>

        <template v-if="configForm.type === 'postgresql' || configForm.type === 'mysql'">
          <el-form-item label="主机地址" required>
            <el-input v-model="configForm.host" :placeholder="configForm.type === 'postgresql' ? 'localhost' : 'localhost'" />
          </el-form-item>
          <el-form-item label="端口" required>
            <el-input-number v-model="configForm.port" :min="1" :max="65535" style="width: 100%;" />
          </el-form-item>
          <el-form-item label="数据库名" required>
            <el-input v-model="configForm.database" placeholder="请输入数据库名" />
          </el-form-item>
          <el-form-item label="用户名" required>
            <el-input v-model="configForm.user" placeholder="请输入用户名" />
          </el-form-item>
          <el-form-item label="密码" required>
            <el-input v-model="configForm.password" type="password" show-password :placeholder="editId ? '留空则不修改密码' : '请输入密码'" />
          </el-form-item>
        </template>

        <template v-if="configForm.type === 'csv'">
          <el-form-item label="文件路径" required>
            <el-input v-model="configForm.file_path" placeholder="D:/data/file.csv">
              <template #prepend>
                <el-button @click="openFsBrowser('file', '.csv')" :icon="Document" />
              </template>
            </el-input>
          </el-form-item>
        </template>

        <template v-if="configForm.type === 'excel'">
          <el-form-item label="数据模式">
            <el-radio-group v-model="configForm.excel_mode">
              <el-radio value="file">单文件</el-radio>
              <el-radio value="folder">文件夹</el-radio>
              <el-radio value="files">多文件</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item v-if="configForm.excel_mode === 'file'" label="文件路径" required>
            <el-input v-model="configForm.file_path" placeholder="D:/data/file.xlsx">
              <template #prepend>
                <el-button @click="openFsBrowser('file', '.xlsx,.xls')" :icon="Document" />
              </template>
            </el-input>
          </el-form-item>
          <el-form-item v-if="configForm.excel_mode === 'folder'" label="文件夹路径" required>
            <el-input v-model="configForm.file_path" placeholder="D:/data/ (该文件夹下所有 .xlsx/.xls 文件将自动作为数据集)">
              <template #prepend>
                <el-button @click="openFsBrowser('folder')" :icon="FolderOpened" />
              </template>
            </el-input>
          </el-form-item>
          <el-form-item v-if="configForm.excel_mode === 'files'" label="文件列表" required>
            <div v-for="(fp, i) in configForm.file_paths" :key="i" class="multi-file-row">
              <el-input :model-value="fp" @update:model-value="(v: string) => configForm.file_paths[i] = v" placeholder="D:/data/file.xlsx">
                <template #prepend>
                  <el-button @click="openFsBrowser('file', '.xlsx,.xls', i)" :icon="Document" />
                </template>
              </el-input>
              <el-button text type="danger" @click="configForm.file_paths.splice(i, 1)">删除</el-button>
            </div>
            <el-button size="small" type="primary" plain @click="configForm.file_paths.push('')">+ 添加文件</el-button>
          </el-form-item>
          <el-form-item label="说明">
            <span style="color:#909399;font-size:12px">多Sheet文件：第一个Sheet用文件名作为数据集名，其余Sheet用 文件名_Sheet名 命名</span>
          </el-form-item>
        </template>

        <template v-if="configForm.type === 'obs'">
          <el-form-item label="终端地址" required>
            <el-input v-model="configForm.endpoint" placeholder="obs.cn-north-4.myhuaweicloud.com" />
          </el-form-item>
          <el-form-item label="Access Key" required>
            <el-input v-model="configForm.access_key" placeholder="请输入 AK" />
          </el-form-item>
          <el-form-item label="Secret Key" required>
            <el-input v-model="configForm.secret_key" type="password" show-password placeholder="请输入 SK" />
          </el-form-item>
          <el-form-item label="桶名称">
            <el-input v-model="configForm.bucket" placeholder="my-bucket" />
          </el-form-item>
          <el-form-item label="HTTPS">
            <el-switch v-model="configForm.secure" />
          </el-form-item>
        </template>

        <template v-if="configForm.type === 'hadoop'">
          <el-form-item label="主机地址" required>
            <el-input v-model="configForm.host" placeholder="namenode-host" />
          </el-form-item>
          <el-form-item label="端口" required>
            <el-input-number v-model="configForm.port" :min="1" :max="65535" style="width: 100%;" />
          </el-form-item>
          <el-form-item label="用户名" required>
            <el-input v-model="configForm.user" placeholder="hadoop" />
          </el-form-item>
          <el-form-item label="基础路径">
            <el-input v-model="configForm.base_path" placeholder="/user/data" />
          </el-form-item>
        </template>

        <template v-if="configForm.type === 'chroma'">
          <el-form-item label="数据目录" required>
            <el-input v-model="configForm.file_path" placeholder="D:/chroma-data">
              <template #prepend>
                <el-button @click="openFsBrowser('folder')" :icon="FolderOpened" />
              </template>
            </el-input>
          </el-form-item>
          <el-form-item label="说明">
            <span style="color:#909399;font-size:12px">ChromaDB 嵌入式向量库，数据持久化到本地目录。集合（Collection）即数据表。</span>
          </el-form-item>
        </template>
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
import { ref, onMounted, reactive } from 'vue'
import api from '@/api/index'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document, FolderOpened, Refresh } from '@element-plus/icons-vue'
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
const editId = ref<string | null>(null)
const saving = ref(false)
const showFsBrowser = ref(false)
const fsBrowserMode = ref<'file' | 'folder'>('file')
const fsBrowserExt = ref('')
const fsBrowserDefaultPath = ref('D:/')
const fsBrowserTargetIndex = ref(-1)

const defaultPorts: Record<string, number> = {
  postgresql: 5432,
  mysql: 3306,
  hadoop: 9870,
}

const configForm = reactive({
  name: '',
  type: 'postgresql',
  host: 'localhost',
  port: 5432,
  database: '',
  user: '',
  password: '',
  file_path: '',
  file_paths: [] as string[],
  excel_mode: 'file',
  sheet_name: '',
  endpoint: '',
  access_key: '',
  secret_key: '',
  bucket: '',
  secure: true,
  base_path: '/',
})

onMounted(async () => {
  await fetchDataSources()
})

function getTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    postgresql: 'PostgreSQL',
    mysql: 'MySQL',
    csv: 'CSV',
    excel: 'Excel',
    chroma: 'ChromaDB',
    obs: 'OBS',
    hadoop: 'Hadoop',
  }
  return labels[type] || type
}

function getTypeTagType(type: string): string {
  const tagTypes: Record<string, string> = {
    postgresql: '',
    mysql: 'warning',
    csv: 'success',
    excel: 'success',
    chroma: 'danger',
    obs: 'danger',
    hadoop: 'info',
  }
  return tagTypes[type] || ''
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
  configForm.port = defaultPorts[configForm.type] || 0
}

function resetForm() {
  editId.value = null
  configForm.name = ''
  configForm.type = 'postgresql'
  configForm.host = 'localhost'
  configForm.port = 5432
  configForm.database = ''
  configForm.user = ''
  configForm.password = ''
  configForm.file_path = ''
  configForm.file_paths = []
  configForm.excel_mode = 'file'
  configForm.sheet_name = ''
  configForm.endpoint = ''
  configForm.access_key = ''
  configForm.secret_key = ''
  configForm.bucket = ''
  configForm.secure = true
  configForm.base_path = '/'
}

function openCreateDialog() {
  editId.value = null
  resetForm()
  showCreateDialog.value = true
}

function editDataSource(source: any) {
  editId.value = source.id
  configForm.name = source.name
  configForm.type = source.type

  const cfg = source.connection_config || {}

  defaultSet('host', cfg.host || 'localhost')
  defaultSet('port', cfg.port || defaultPorts[source.type] || 0)
  defaultSet('database', cfg.database || '')
  defaultSet('user', cfg.user || '')
  defaultSet('password', '')
  defaultSet('file_path', cfg.file_path || '')
  defaultSet('file_paths', cfg.file_paths || [])
  defaultSet('excel_mode', cfg.mode || 'file')
  defaultSet('sheet_name', cfg.sheet_name || '')
  defaultSet('endpoint', cfg.endpoint || '')
  defaultSet('access_key', '')
  defaultSet('secret_key', '')
  defaultSet('bucket', cfg.bucket || '')
  defaultSet('secure', cfg.secure !== undefined ? cfg.secure : true)
  defaultSet('base_path', cfg.base_path || '/')

  showCreateDialog.value = true
}

function defaultSet(key: string, value: any) {
  ;(configForm as any)[key] = value
}

function buildConnectionConfig(): Record<string, any> {
  const type = configForm.type
  switch (type) {
    case 'postgresql':
    case 'mysql': {
      const cfg: Record<string, any> = {
        host: configForm.host,
        port: configForm.port,
        database: configForm.database,
        user: configForm.user,
      }
      if (configForm.password) {
        cfg.password = configForm.password
      }
      return cfg
    }
    case 'csv':
      return { file_path: configForm.file_path }
    case 'excel': {
      const mode = configForm.excel_mode
      const cfg: Record<string, any> = { mode }
      if (mode === 'folder') {
        cfg.file_path = configForm.file_path
      } else if (mode === 'files') {
        cfg.file_paths = configForm.file_paths
        cfg.file_path = configForm.file_paths[0] || ''
      } else {
        cfg.file_path = configForm.file_path
      }
      return cfg
    }
    case 'chroma':
      return { persist_directory: configForm.file_path || 'd:/chroma-data' }
    case 'obs': {
      const cfg: Record<string, any> = {
        endpoint: configForm.endpoint,
        bucket: configForm.bucket,
        secure: configForm.secure,
      }
      if (configForm.access_key) cfg.access_key = configForm.access_key
      if (configForm.secret_key) cfg.secret_key = configForm.secret_key
      return cfg
    }
    case 'hadoop':
      return {
        host: configForm.host,
        port: configForm.port,
        user: configForm.user,
        base_path: configForm.base_path,
      }
    default:
      return {}
  }
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
    ElMessage.success(`元数据同步完成: ${res.synced} 张表`)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '同步失败')
  } finally {
    row._syncing = false
  }
}

function openFsBrowser(mode: 'file' | 'folder', ext = '', targetIndex = -1) {
  fsBrowserMode.value = mode
  fsBrowserExt.value = ext
  fsBrowserTargetIndex.value = targetIndex
  fsBrowserDefaultPath.value = configForm.file_path || 'D:/'
  showFsBrowser.value = true
}

function onFsSelect(path: string) {
  if (fsBrowserTargetIndex.value >= 0) {
    configForm.file_paths[fsBrowserTargetIndex.value] = path
  } else {
    configForm.file_path = path
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
