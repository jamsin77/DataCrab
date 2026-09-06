<template>
  <div class="filelink-container">
    <div class="toolbar">
      <el-button type="primary" @click="showCreateDialog = true">
        <el-icon><Plus /></el-icon> {{ t('filelink.createFileLink') }}
      </el-button>
    </div>

    <el-table :data="fileLinks" stripe>
      <el-table-column prop="name" :label="t('filelink.name')" width="200" />
      <el-table-column prop="path" :label="t('filelink.path')" show-overflow-tooltip />
      <el-table-column prop="link_type" :label="t('common.type')" width="100">
        <template #default="{ row }">
          <el-tag :type="row.link_type === 'directory' ? 'primary' : 'success'">
            {{ row.link_type === 'directory' ? t('filelink.directory') : t('filelink.file') }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="is_public" :label="t('filelink.isPublic')" width="80">
        <template #default="{ row }">
          <el-tag :type="row.is_public ? 'success' : 'info'" size="small">
            {{ row.is_public ? t('common.yes') : t('common.no') }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" :label="t('common.createdAt')" width="180" />
      <el-table-column :label="t('common.actions')" width="280">
        <template #default="{ row }">
          <el-button size="small" @click="browseLink(row)">{{ t('filelink.browse') }}</el-button>
          <el-button size="small" type="primary" @click="editLink(row)">{{ t('common.edit') }}</el-button>
          <el-button size="small" type="danger" @click="deleteLink(row.id)">{{ t('common.delete') }}</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 创建/编辑对话框 -->
    <el-dialog v-model="showCreateDialog" :title="editingLink ? t('filelink.editLink') : t('filelink.createFileLink')" width="500px">
      <el-form :model="createForm" label-width="100px">
        <el-form-item :label="t('filelink.name')" required>
          <el-input v-model="createForm.name" :placeholder="t('filelink.linkName')" />
        </el-form-item>
        <el-form-item :label="t('filelink.path')" required>
          <el-input v-model="createForm.path" :placeholder="t('filelink.pathPlaceholder')">
            <template #append>
              <el-button @click="selectPath">{{ t('fileBrowser.select') }}</el-button>
            </template>
          </el-input>
        </el-form-item>
        <el-form-item :label="t('filelink.description')">
          <el-input v-model="createForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item :label="t('filelink.publicAccess')">
          <el-switch v-model="createForm.is_public" />
        </el-form-item>
        <el-form-item :label="t('filelink.allowedExtensions')">
          <el-input v-model="createForm.extensionsStr" :placeholder="t('filelink.extensionsPlaceholder')" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="saveLink">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <!-- 浏览对话框 -->
    <el-dialog v-model="showBrowseDialog" :title="browsingLink?.name" width="800px">
      <div class="browse-header">
        <el-breadcrumb separator="/">
          <el-breadcrumb-item v-for="(part, idx) in browsePath.split('/').filter(Boolean)" :key="idx">
            {{ part }}
          </el-breadcrumb-item>
        </el-breadcrumb>
      </div>
      <el-table :data="browseFiles" stripe max-height="400">
        <el-table-column :label="t('filelink.name')" width="300">
          <template #default="{ row }">
            <div class="file-item" @click="navigateTo(row)">
              <el-icon v-if="row.is_dir"><Folder /></el-icon>
              <el-icon v-else><Document /></el-icon>
              <span>{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="size" :label="t('fileBrowser.size')" width="120">
          <template #default="{ row }">
            {{ row.size ? formatSize(row.size) : '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="modified_time" :label="t('fileBrowser.modified')" width="180" />
        <el-table-column :label="t('common.actions')" width="150">
          <template #default="{ row }">
            <el-button v-if="row.is_file" size="small" @click="previewFile(row)">{{ t('common.preview') }}</el-button>
            <el-button v-if="row.is_file" size="small" type="primary" @click="downloadFile(row)">{{ t('common.download') }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- 预览对话框 -->
    <el-dialog v-model="showPreviewDialog" :title="previewingFile?.name" width="800px">
      <pre class="preview-content">{{ previewContent }}</pre>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '@/api/index'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useI18n } from 'vue-i18n'

interface FileLink {
  id: string
  name: string
  path: string
  description?: string
  link_type: string
  is_public: boolean
  allowed_extensions?: string[]
  created_at: string
}

interface FileInfo {
  name: string
  path: string
  is_file: boolean
  is_dir: boolean
  size?: number
  modified_time?: string
}

const { t } = useI18n()

const fileLinks = ref<FileLink[]>([])
const showCreateDialog = ref(false)
const showBrowseDialog = ref(false)
const showPreviewDialog = ref(false)
const editingLink = ref<FileLink | null>(null)
const browsingLink = ref<FileLink | null>(null)
const browsePath = ref('')
const browseFiles = ref<FileInfo[]>([])
const previewContent = ref('')
const previewingFile = ref<FileInfo | null>(null)

const createForm = ref({
  name: '',
  path: '',
  description: '',
  is_public: false,
  extensionsStr: '',
})

function extractError(e: any): string {
  if (e?.response?.data?.detail) {
    const detail = e.response.data.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map((d: any) => d.msg || String(d)).join('; ')
  }
  return e?.message || t('common.operationFailed')
}

function formatSize(size: number): string {
  if (size < 1024) return size + ' B'
  if (size < 1024 * 1024) return (size / 1024).toFixed(1) + ' KB'
  if (size < 1024 * 1024 * 1024) return (size / 1024 / 1024).toFixed(1) + ' MB'
  return (size / 1024 / 1024 / 1024).toFixed(1) + ' GB'
}

onMounted(async () => {
  await fetchFileLinks()
})

async function fetchFileLinks() {
  try {
    fileLinks.value = await api.get('/filelinks')
  } catch (e: any) {
    ElMessage.error(extractError(e))
  }
}

function selectPath() {
  // 在实际应用中，这里可以打开一个文件选择对话框
  // 由于浏览器安全限制，需要使用后端提供的路径浏览功能
  ElMessage.info(t('filelink.pathHint'))
}

async function saveLink() {
  if (!createForm.value.name || !createForm.value.path) {
    ElMessage.warning(t('filelink.nameAndPathRequired'))
    return
  }
  
  try {
    const data: any = {
      name: createForm.value.name,
      path: createForm.value.path,
      description: createForm.value.description,
      is_public: createForm.value.is_public,
    }
    
    if (createForm.value.extensionsStr) {
      data.allowed_extensions = createForm.value.extensionsStr.split(',').map(s => s.trim())
    }
    
    if (editingLink.value) {
      await api.put(`/filelinks/${editingLink.value.id}`, data)
      ElMessage.success(t('common.updateSuccess'))
    } else {
      await api.post('/filelinks', data)
      ElMessage.success(t('common.createSuccess'))
    }
    
    showCreateDialog.value = false
    resetForm()
    await fetchFileLinks()
  } catch (e: any) {
    ElMessage.error(extractError(e))
  }
}

function editLink(link: FileLink) {
  editingLink.value = link
  createForm.value = {
    name: link.name,
    path: link.path,
    description: link.description || '',
    is_public: link.is_public,
    extensionsStr: link.allowed_extensions?.join(',') || '',
  }
  showCreateDialog.value = true
}

async function deleteLink(id: string) {
  try {
    await ElMessageBox.confirm(t('filelink.deleteConfirm'), t('filelink.deleteTitle'), { type: 'warning' })
    await api.delete(`/filelinks/${id}`)
    ElMessage.success(t('filelink.deleteSuccess'))
    await fetchFileLinks()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(extractError(e))
    }
  }
}

async function browseLink(link: FileLink) {
  browsingLink.value = link
  browsePath.value = ''
  await loadBrowseContent()
  showBrowseDialog.value = true
}

async function loadBrowseContent() {
  if (!browsingLink.value) return
  try {
    const res = await api.get(`/filelinks/${browsingLink.value.id}/browse`, {
      params: { subpath: browsePath.value }
    })
    browseFiles.value = res.files
  } catch (e: any) {
    ElMessage.error(extractError(e))
  }
}

async function navigateTo(file: FileInfo) {
  if (file.is_dir) {
    browsePath.value = browsePath.value ? `${browsePath.value}/${file.name}` : file.name
    await loadBrowseContent()
  }
}

async function previewFile(file: FileInfo) {
  if (!browsingLink.value) return
  try {
    const res = await api.get(`/filelinks/${browsingLink.value.id}/preview`, {
      params: { subpath: browsePath.value ? `${browsePath.value}/${file.name}` : file.name }
    })
    previewContent.value = res.content
    previewingFile.value = file
    showPreviewDialog.value = true
  } catch (e: any) {
    ElMessage.error(extractError(e))
  }
}

async function downloadFile(file: FileInfo) {
  if (!browsingLink.value) return
  const subpath = browsePath.value ? `${browsePath.value}/${file.name}` : file.name
  try {
    const token = localStorage.getItem('access_token')
    const response = await fetch(`/api/v1/filelinks/${browsingLink.value.id}/download?subpath=${encodeURIComponent(subpath)}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!response.ok) throw new Error(t('filelink.downloadFailed'))
    const blob = await response.blob()
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = file.name
    a.click()
    window.URL.revokeObjectURL(url)
  } catch (e: any) {
    ElMessage.error(extractError(e))
  }
}

function resetForm() {
  editingLink.value = null
  createForm.value = {
    name: '',
    path: '',
    description: '',
    is_public: false,
    extensionsStr: '',
  }
}
</script>

<style lang="scss" scoped>
.filelink-container {
  padding: 20px;
  background: #fff;
  border-radius: 8px;
}

.toolbar {
  margin-bottom: 16px;
}

.browse-header {
  margin-bottom: 16px;
  padding: 8px;
  background: #f5f7fa;
  border-radius: 4px;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  
  &:hover {
    color: #409eff;
  }
}

.preview-content {
  max-height: 500px;
  overflow: auto;
  padding: 16px;
  background: #f5f7fa;
  border-radius: 4px;
  font-size: 13px;
  line-height: 1.5;
}
</style>
