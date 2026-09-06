<template>
  <div class="asset-manager">
    <el-alert type="info" :closable="false" show-icon style="margin-bottom: 16px">
      {{ t('config.asset.exportHint') }}
    </el-alert>

    <el-row :gutter="20">
      <!-- 导出 -->
      <el-col :span="12">
        <el-card>
          <template #header>
            <span style="font-weight: bold">{{ t('config.asset.export') }}</span>
          </template>
          <p style="color: #909399; margin-bottom: 16px">{{ t('config.asset.selectExportTypes') }}</p>
          <el-checkbox v-model="exportAll" :indeterminate="exportIndeterminate" @change="toggleExportAll" style="margin-bottom: 4px; font-weight: bold">
            {{ t('config.asset.selectAllOrNone') }}
          </el-checkbox>
          <el-checkbox-group v-model="exportTypes" @change="onExportTypesChange" style="display: flex; flex-direction: column; gap: 8px; margin-left: 8px">
            <el-checkbox label="skills">{{ t('config.asset.skills') }}（{{ counts.skills }} {{ t('config.asset.unit') }}）</el-checkbox>
            <el-checkbox label="operators">{{ t('config.asset.operators') }}（{{ counts.operators }} {{ t('config.asset.unit') }}）</el-checkbox>
            <el-checkbox label="pipelines">{{ t('config.asset.pipelines') }}（{{ counts.pipelines }} {{ t('config.asset.unit') }}）</el-checkbox>
            <el-checkbox label="llm_config">{{ t('config.asset.llmProvider') }}（{{ counts.llm_config }} {{ t('config.asset.unit') }}）</el-checkbox>
            <el-checkbox label="custom_extensions">{{ t('config.asset.customConnector') }}（{{ counts.custom_extensions }} {{ t('config.asset.unit') }}）</el-checkbox>
            <el-checkbox label="datasources">{{ t('config.asset.datasources') }}（{{ counts.datasources }} {{ t('config.asset.unit') }}）</el-checkbox>
            <el-checkbox label="schedules">{{ t('config.asset.schedules') }}（{{ counts.schedules }} {{ t('config.asset.unit') }}）</el-checkbox>
          </el-checkbox-group>
          <el-button type="primary" :loading="exporting" :disabled="!exportTypes.length" @click="doExport" style="margin-top: 16px">
            {{ t('config.asset.exportZip') }}
          </el-button>
        </el-card>
      </el-col>

      <!-- 导入 -->
      <el-col :span="12">
        <el-card>
          <template #header>
            <span style="font-weight: bold">{{ t('config.asset.import') }}</span>
          </template>
          <el-upload :show-file-list="false" :before-upload="onFileSelected" accept=".zip">
            <el-button type="primary" plain>{{ t('config.asset.selectZip') }}</el-button>
          </el-upload>
          <div v-if="selectedFile" style="margin-top: 12px; display: flex; align-items: center; gap: 8px">
            <el-icon><Document /></el-icon>
            <span style="color: #606266">{{ selectedFile.name }}</span>
            <el-tag size="small" type="info">{{ (selectedFile.size / 1024).toFixed(1) }} KB</el-tag>
          </div>
          <div v-if="previewManifest" style="margin-top: 16px">
            <p style="color: #909399; margin-bottom: 8px">{{ t('config.asset.detectedAssets') }}</p>
            <div style="display: flex; align-items: center; gap: 24px; margin-bottom: 4px">
              <el-checkbox v-model="importAllComputed" :indeterminate="importIndeterminateComputed" style="flex: 1; font-weight: bold">
                {{ t('config.asset.selectAll') }}
              </el-checkbox>
              <el-checkbox v-model="overwriteAllComputed" :indeterminate="overwriteIndeterminateComputed" size="small">
                {{ t('config.asset.selectAllOverwrite') }}
              </el-checkbox>
            </div>
            <div style="display: flex; flex-direction: column; gap: 8px; margin-left: 8px">
              <div v-for="(v, k) in previewManifest.counts" :key="k" style="display: flex; align-items: center; gap: 24px">
                <el-checkbox :model-value="importTypes.includes(k)" @update:model-value="toggleImportType(k, $event)" style="flex: 1">
                  {{ typeLabel(k) }}（{{ v }} {{ t('config.asset.unit') }}）
                </el-checkbox>
                <el-checkbox :model-value="overwriteTypes.includes(k)" @update:model-value="toggleOverwriteType(k, $event)" :disabled="!importTypes.includes(k)" size="small">
                  {{ t('config.asset.overwriteLabel') }}
                </el-checkbox>
              </div>
            </div>
            <div style="margin-top: 16px">
              <el-button type="success" :loading="importing" :disabled="!importTypes.length" @click="doImport">
                {{ t('config.asset.importSelected') }}
              </el-button>
              <el-button @click="resetImport" style="margin-left: 8px">{{ t('common.cancel') }}</el-button>
            </div>
          </div>
          <div v-if="importResult" style="margin-top: 16px">
            <el-divider />
            <p style="font-weight: bold; margin-bottom: 8px">{{ t('config.asset.importResultTitle') }}</p>
            <el-tag v-for="(v, k) in importResult" :key="k" :type="v.skipped ? 'warning' : 'success'" style="margin: 2px">
              {{ typeLabel(k) }}：{{ t('config.asset.imported') }} {{ v.imported }}<template v-if="v.updated"> / {{ t('config.asset.updated') }} {{ v.updated }}</template> / {{ t('config.asset.skipped') }} {{ v.skipped }}
            </el-tag>
            <el-alert type="warning" :closable="false" show-icon style="margin-top: 12px" v-if="importTypes.includes('llm_config')">
              {{ t('config.asset.llmKeyHint') }}
            </el-alert>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Document } from '@element-plus/icons-vue'
import api from '@/api/index'

const { t } = useI18n()
const exportTypes = ref<string[]>([])
const exportAll = ref(false)
const exportIndeterminate = ref(false)
const importing = ref(false)
const exporting = ref(false)
const importTypes = ref<string[]>([])
const overwriteTypes = ref<string[]>([])
const previewManifest = ref<any>(null)
const importResult = ref<any>(null)
const selectedFile = ref<File | null>(null)
const counts = ref({ skills: 0, operators: 0, pipelines: 0, llm_config: 0, custom_extensions: 0, datasources: 0, schedules: 0 })

const ALL_TYPES = ['skills', 'operators', 'pipelines', 'llm_config', 'custom_extensions', 'datasources', 'schedules']

const manifestKeys = computed(() => previewManifest.value ? Object.keys(previewManifest.value.counts) : [])

const importAllComputed = computed({
  get: () => manifestKeys.value.length > 0 && importTypes.value.length === manifestKeys.value.length,
  set: (val: boolean) => {
    if (val) {
      importTypes.value = [...manifestKeys.value]
    } else {
      importTypes.value = []
      overwriteTypes.value = []
    }
  },
})

const importIndeterminateComputed = computed(() => importTypes.value.length > 0 && importTypes.value.length < manifestKeys.value.length)

const overwriteAllComputed = computed({
  get: () => importTypes.value.length > 0 && overwriteTypes.value.length === importTypes.value.length,
  set: (val: boolean) => {
    overwriteTypes.value = val ? [...importTypes.value] : []
  },
})

const overwriteIndeterminateComputed = computed(() => overwriteTypes.value.length > 0 && overwriteTypes.value.length < importTypes.value.length)

onMounted(() => {
  loadCounts()
})

async function loadCounts() {
  try {
    const data = await api.get('/assets/counts')
    counts.value = { skills: 0, operators: 0, pipelines: 0, llm_config: 0, custom_extensions: 0, datasources: 0, schedules: 0, ...data }
  } catch (e) {
    // counts 接口可选，失败不报错
  }
}

function typeLabel(k: string): string {
  const m: Record<string, string> = {
    skills: t('config.asset.skills'), operators: t('config.asset.operators'), pipelines: t('config.asset.pipelines'),
    llm_config: t('config.asset.llmProvider'), custom_extensions: t('config.asset.customConnector'), datasources: t('config.asset.datasources'), schedules: t('config.asset.schedules'),
  }
  return m[k] || k
}

function extractErr(e: any): string {
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d: any) => d?.msg || JSON.stringify(d)).join('; ')
  return e?.message || t('config.asset.unknownError')
}

function toggleExportAll(val: boolean) {
  exportTypes.value = val ? [...ALL_TYPES] : []
  exportIndeterminate.value = false
}

function toggleImportType(k: string, checked: boolean) {
  if (checked) {
    if (!importTypes.value.includes(k)) importTypes.value.push(k)
  } else {
    importTypes.value = importTypes.value.filter(t => t !== k)
    overwriteTypes.value = overwriteTypes.value.filter(t => t !== k)
  }
}

function toggleOverwriteType(k: string, checked: boolean) {
  if (checked) {
    if (!overwriteTypes.value.includes(k)) overwriteTypes.value.push(k)
  } else {
    overwriteTypes.value = overwriteTypes.value.filter(t => t !== k)
  }
}

function onExportTypesChange(val: string[]) {
  if (val.length === 0) {
    exportAll.value = false
    exportIndeterminate.value = false
  } else if (val.length === ALL_TYPES.length) {
    exportAll.value = true
    exportIndeterminate.value = false
  } else {
    exportAll.value = false
    exportIndeterminate.value = true
  }
}

async function doExport() {
  exporting.value = true
  try {
    const blob = await api.post('/assets/export', { types: exportTypes.value }, { responseType: 'blob' }) as unknown as Blob
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    const d = new Date()
    const ts = `${d.getFullYear()}${String(d.getMonth()+1).padStart(2,'0')}${String(d.getDate()).padStart(2,'0')}_${String(d.getHours()).padStart(2,'0')}${String(d.getMinutes()).padStart(2,'0')}${String(d.getSeconds()).padStart(2,'0')}`
    a.download = `datacrab_${ts}.zip`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success(t('config.asset.exportSuccess'))
  } catch (e: any) {
    ElMessage.error(t('config.asset.exportFailed') + ': ' + extractErr(e))
  } finally {
    exporting.value = false
  }
}

async function onFileSelected(file: File) {
  selectedFile.value = file
  importResult.value = null
  importTypes.value = []
  overwriteTypes.value = []
  try {
    const fd = new FormData()
    fd.append('file', file)
    const data = await api.post('/assets/import/preview', fd) as any
    previewManifest.value = data
    if (previewManifest.value?.counts) {
      importTypes.value = Object.keys(previewManifest.value.counts)
    }
  } catch (e: any) {
    ElMessage.error(t('config.asset.readZipFailed') + ': ' + extractErr(e))
  }
  return false // 阻止自动上传
}

async function doImport() {
  if (!selectedFile.value) return
  importing.value = true
  try {
    const fd = new FormData()
    fd.append('file', selectedFile.value)
    fd.append('types', importTypes.value.join(','))
    fd.append('overwrite_types', overwriteTypes.value.join(','))
    const data = await api.post('/assets/import', fd) as any
    importResult.value = data
    ElMessage.success(t('config.asset.importComplete'))
    loadCounts()
  } catch (e: any) {
    ElMessage.error(t('config.asset.importFailed') + ': ' + extractErr(e))
  } finally {
    importing.value = false
  }
}

function resetImport() {
  previewManifest.value = null
  importResult.value = null
  importTypes.value = []
  overwriteTypes.value = []
  selectedFile.value = null
}
</script>

<style lang="scss" scoped>
.asset-manager {
  max-width: 1000px;
}
</style>
