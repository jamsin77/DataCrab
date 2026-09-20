<template>
  <div class="metadata-page">
    <!-- 左侧：按数据源浏览 -->
    <div class="ds-sidebar">
      <div class="ds-sidebar-title">
        <span>{{ t('metadata.datasource') }}</span>
        <el-button size="small" text @click="loadDatasources">
          <el-icon><Refresh /></el-icon>
        </el-button>
      </div>
      <el-tooltip
        v-for="ds in datasources"
        :key="ds.id"
        :content="ds.name"
        placement="right"
        :show-after="300"
      >
        <div
          class="ds-item"
          :class="{ active: filterDataSource === ds.id }"
          @click="selectDataSource(ds.id)"
        >
          <el-icon><Connection /></el-icon>
          <span class="ds-item-label">{{ ds.name }}</span>
        </div>
      </el-tooltip>
      <el-empty v-if="!datasources.length" :description="t('metadata.noDatasources')" :image-size="50" />
    </div>

    <!-- 右侧：表格与搜索 -->
    <div class="ds-main">
      <div class="page-header">
        <h2>{{ t('metadata.title') }}</h2>
        <div class="header-actions">
          <el-input v-model="searchQuery" :placeholder="t('metadata.searchHint')" clearable style="width: 280px" @clear="loadMetadata" @keyup.enter="loadMetadata">
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-button type="success" @click="batchEnrich" :disabled="!selectedRows.length || batchEnriching">
            {{ t('metadata.batchAiEnrich') }}<template v-if="selectedRows.length">({{ selectedRows.length }})</template>
          </el-button>
          <el-button type="primary" @click="loadMetadata">{{ t('common.refresh') }}</el-button>
        </div>
      </div>

    <div class="stats-bar" v-if="stats">
      <el-tag type="info">{{ t('metadata.totalDatasets', { count: stats.total }) }}</el-tag>
      <el-tag type="success">{{ t('metadata.aiEnrichedCount', { count: stats.ai_enriched }) }}</el-tag>
      <el-tag v-for="(count, fmt) in stats.by_format" :key="fmt" type="warning">{{ fmt }}: {{ count }}</el-tag>
    </div>

    <el-table :data="metadataList" v-loading="loading" style="width: 100%" @row-click="openDetail" @selection-change="handleSelectionChange">
      <el-table-column type="selection" width="42" />
      <el-table-column :label="t('metadata.datasetName')" min-width="160">
        <template #default="{ row }">
          <span class="table-name">{{ row.business_name || row.table_name }}</span>
          <div class="table-name-sub">{{ row.table_name }}</div>
        </template>
      </el-table-column>
      <el-table-column :label="t('metadata.datasource')" width="120" prop="data_source_name" />
      <el-table-column :label="t('metadata.format')" width="80" prop="storage_format" />
      <el-table-column :label="t('metadata.rowCount')" width="90" align="right">
        <template #default="{ row }">{{ formatNumber(row.row_count) }}</template>
      </el-table-column>
      <el-table-column :label="t('metadata.columnCount')" width="70" align="right" prop="column_count" />
      <el-table-column :label="t('metadata.businessTags')" min-width="160">
        <template #default="{ row }">
          <el-tag v-for="tag in (row.business_tags || [])" :key="tag" size="small" style="margin-right: 4px">{{ tag }}</el-tag>
          <span v-if="!row.business_tags?.length" class="text-muted">{{ t('metadata.notSet') }}</span>
        </template>
      </el-table-column>
      <el-table-column label="AI" width="50" align="center">
        <template #default="{ row }">
          <el-icon v-if="row.ai_enriched" color="#67c23a"><CircleCheckFilled /></el-icon>
        </template>
      </el-table-column>
      <el-table-column :label="t('metadata.syncTime')" width="150">
        <template #default="{ row }">{{ formatTime(row.last_synced_at) }}</template>
      </el-table-column>
      <el-table-column :label="t('common.actions')" width="120" align="center">
        <template #default="{ row }">
          <el-button size="small" text type="primary" @click.stop="openDetail(row)">{{ t('common.detail') }}</el-button>
          <el-button size="small" text type="success" @click.stop="aiEnrich(row)">{{ t('metadata.aiEnrich') }}</el-button>
        </template>
      </el-table-column>
    </el-table>
    </div>

    <el-drawer v-model="detailDrawer" :title="detailData?.business_name || detailData?.table_name || t('metadata.detailTitle')" size="60%">
      <div v-if="detailData" class="detail-layout">
        <div class="detail-section">
          <div class="section-header">
            <span>{{ t('metadata.technicalMetadata') }}</span>
            <el-button size="small" type="primary" plain @click="syncOne(detailData.data_source_id)" :disabled="syncing">{{ t('metadata.resync') }}</el-button>
          </div>
          <el-descriptions :column="2" border>
            <el-descriptions-item :label="t('metadata.datasetName')">{{ detailData.table_name }}</el-descriptions-item>
            <el-descriptions-item :label="t('metadata.businessName')">{{ detailData.business_name || '—' }}</el-descriptions-item>
            <el-descriptions-item :label="t('common.type')">{{ detailData.table_type || '—' }}</el-descriptions-item>
            <el-descriptions-item :label="t('metadata.format')">{{ detailData.storage_format || '—' }}</el-descriptions-item>
            <el-descriptions-item :label="t('metadata.storageLocation')" :span="2"><code>{{ detailData.storage_location || '—' }}</code></el-descriptions-item>
            <el-descriptions-item :label="t('metadata.rowCount')">{{ formatNumber(detailData.row_count) }}</el-descriptions-item>
            <el-descriptions-item :label="t('metadata.columnCount')">{{ detailData.column_count }}</el-descriptions-item>
          </el-descriptions>

          <div v-if="detailData.table_schema?.length" class="schema-table">
            <div class="sub-title">{{ t('metadata.fieldDefinition') }}</div>
            <el-table :data="detailData.table_schema" size="small" border>
              <el-table-column :label="t('metadata.columnName')" prop="name" min-width="120" />
              <el-table-column :label="t('common.type')" prop="dtype" width="120" />
              <el-table-column :label="t('metadata.nullable')" width="60" align="center">
                <template #default="{ row }">{{ row.nullable ? t('metadata.yes') : t('metadata.no') }}</template>
              </el-table-column>
            </el-table>
          </div>

          <el-collapse v-if="detailData.sample_data?.length" style="margin-top: 12px">
            <el-collapse-item :title="t('metadata.sampleData')">
              <pre>{{ JSON.stringify(detailData.sample_data, null, 2) }}</pre>
            </el-collapse-item>
          </el-collapse>
        </div>

        <div class="detail-section">
          <div class="section-header">
            <span>{{ t('metadata.businessMetadata') }}</span>
            <el-button size="small" type="success" @click="aiEnrich(detailData)">{{ t('metadata.aiEnrich') }}</el-button>
          </div>
          <el-form label-width="100px">
            <el-form-item :label="t('metadata.businessName')">
              <el-input v-model="editForm.business_name" :placeholder="t('metadata.businessNamePlaceholder')" />
            </el-form-item>
            <el-form-item :label="t('metadata.businessDescription')">
              <el-input v-model="editForm.business_description" type="textarea" :rows="2" />
            </el-form-item>
            <el-form-item :label="t('metadata.businessTags')">
              <el-select v-model="editForm.business_tags" multiple filterable allow-create default-first-option style="width: 100%" :placeholder="t('metadata.addTag')">
              </el-select>
            </el-form-item>
            <el-form-item :label="t('metadata.businessPurpose')">
              <el-input v-model="editForm.business_purpose" type="textarea" :rows="2" />
            </el-form-item>
            <el-form-item :label="t('metadata.sourceSystem')">
              <el-input v-model="editForm.source_system" />
            </el-form-item>
            <el-form-item :label="t('metadata.dataDomain')">
              <el-input v-model="editForm.data_domain" />
            </el-form-item>
            <el-form-item :label="t('metadata.dataOwner')">
              <el-input v-model="editForm.data_owner" />
            </el-form-item>
            <el-form-item :label="t('metadata.securityLevel')">
              <el-select v-model="editForm.security_level" style="width: 100%">
                <el-option :label="t('metadata.public')" value="public" />
                <el-option :label="t('metadata.internal')" value="internal" />
                <el-option :label="t('metadata.confidential')" value="confidential" />
                <el-option :label="t('metadata.secret')" value="secret" />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="saveDetail" :disabled="saving">{{ t('metadata.saveChanges') }}</el-button>
            </el-form-item>
          </el-form>
        </div>
      </div>
    </el-drawer>

    <!-- AI 增强进度弹窗（居中，并发处理） -->
    <el-dialog
      v-model="enrichDialog.visible"
      :title="enrichDialogTitle"
      width="720px"
      top="8vh"
      :close-on-click-modal="!enrichDialog.processing"
      :close-on-press-escape="true"
      :show-close="true"
      class="enrich-dialog"
      @close="onEnrichDialogClose"
    >
      <div class="enrich-summary">
        <span class="enrich-summary-item">
          <el-icon color="#409eff"><DataAnalysis /></el-icon>
          总计 {{ enrichDialog.tables.length }}
        </span>
        <span class="enrich-summary-item">
          <el-icon color="#67c23a"><CircleCheckFilled /></el-icon>
          成功 {{ enrichDoneCount }}
        </span>
        <span class="enrich-summary-item" v-if="enrichErrorCount">
          <el-icon color="#f56c6c"><CircleCloseFilled /></el-icon>
          失败 {{ enrichErrorCount }}
        </span>
        <span class="enrich-summary-item" v-if="enrichDialog.processing">
          <el-icon class="is-loading"><Loading /></el-icon>
          进行中 {{ enrichProcessingCount }}
        </span>
      </div>

      <div class="enrich-table-list">
        <div v-for="tbl in enrichDialog.tables" :key="tbl.id" class="enrich-table-item">
          <div class="enrich-table-header" @click="tbl.collapsed = !tbl.collapsed">
            <el-icon v-if="tbl.status === 'processing'" class="is-loading"><Loading /></el-icon>
            <el-icon v-else-if="tbl.status === 'done'" color="#67c23a"><CircleCheckFilled /></el-icon>
            <el-icon v-else-if="tbl.status === 'error'" color="#f56c6c"><CircleCloseFilled /></el-icon>
            <el-icon v-else color="#909399"><Clock /></el-icon>
            <span class="enrich-table-name">{{ tbl.name }}</span>
            <el-icon class="enrich-collapse-icon" :class="{ 'is-rotated': !tbl.collapsed }"><CaretRight /></el-icon>
          </div>
          <div v-show="!tbl.collapsed && tbl.logs.length" class="enrich-table-logs">
            <div v-for="(log, i) in tbl.logs" :key="i" class="enrich-log-line">{{ log }}</div>
          </div>
          <div v-if="tbl.status === 'error' && tbl.errorMsg" class="enrich-table-error">{{ tbl.errorMsg }}</div>
          <div v-if="tbl.status === 'done' && tbl.result" class="enrich-table-result">
            <el-tag size="small" type="success">{{ tbl.result.business_name || '—' }}</el-tag>
            <span v-if="tbl.result.business_tags?.length" class="enrich-result-tags">
              <el-tag v-for="tag in tbl.result.business_tags" :key="tag" size="small" type="info" effect="plain">{{ tag }}</el-tag>
            </span>
          </div>
        </div>
      </div>

      <template #footer>
        <el-button v-if="enrichDialog.processing" type="warning" @click="onEnrichDialogClose">
          中止并关闭
        </el-button>
        <el-button v-else type="primary" @click="enrichDialog.visible = false">
          {{ t('common.confirm') }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { Search, CircleCheckFilled, CircleCloseFilled, Loading, Connection, Refresh, ArrowDown, ArrowRight, DataAnalysis, Clock, CaretRight } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import api from '@/api/index'
import { ElMessage, ElMessageBox } from 'element-plus'

const { t } = useI18n()

const loading = ref(false)
const metadataList = ref<any[]>([])
const datasources = ref<any[]>([])
const filterDataSource = ref('')
const searchQuery = ref('')
const stats = ref<any>(null)
const currentPage = ref(1)
const pageSize = ref(20)
const total = ref(0)

const detailDrawer = ref(false)
const detailData = ref<any>(null)
const editForm = reactive<any>({})
const saving = ref(false)
const enriching = ref(false)
const syncing = ref(false)
const dsLoading = ref(false)
const selectedRows = ref<any[]>([])
const batchEnriching = ref(false)
const enrichAbortController = ref<AbortController | null>(null)

function onEnrichDialogClose() {
  if (enrichAbortController.value) {
    enrichAbortController.value.abort()
    enrichAbortController.value = null
  }
  enrichDialog.processing = false
  enrichDialog.tables.forEach(t => {
    if (t.status === 'processing' || t.status === 'pending') {
      t.status = 'error'
      t.errorMsg = '已中止'
    }
  })
}

// AI 增强弹窗（居中，并发处理）
const enrichDialog = reactive<{
  visible: boolean
  processing: boolean
  tables: Array<{
    id: string
    name: string
    status: 'pending' | 'processing' | 'done' | 'error'
    logs: string[]
    errorMsg: string
    result: any
    collapsed: boolean
  }>
}>({
  visible: false,
  processing: false,
  tables: [],
})

const enrichDoneCount = computed(() => enrichDialog.tables.filter(t => t.status === 'done').length)
const enrichErrorCount = computed(() => enrichDialog.tables.filter(t => t.status === 'error').length)
const enrichProcessingCount = computed(() => enrichDialog.tables.filter(t => t.status === 'processing' || t.status === 'pending').length)
const enrichDialogTitle = computed(() => {
  if (enrichDialog.processing) return `AI 增强中（${enrichDoneCount.value}/${enrichDialog.tables.length}）`
  if (enrichErrorCount.value > 0) return `AI 增强完成（成功 ${enrichDoneCount.value}，失败 ${enrichErrorCount.value}）`
  return `AI 增强完成（${enrichDoneCount.value} 项）`
})

async function enrichStreamConcurrent(rows: any[]) {
  const ids = rows.map(r => r.id)
  const token = localStorage.getItem('access_token')

  enrichDialog.visible = true
  enrichDialog.processing = true
  enrichDialog.tables = rows.map(r => ({
    id: r.id,
    name: r.business_name || r.table_name || r.id,
    status: 'pending' as const,
    logs: [],
    errorMsg: '',
    result: null as any,
    collapsed: true,
  }))

  const ac = new AbortController()
  enrichAbortController.value = ac

  const res = await fetch(`/api/v1/metadata/batch-ai-enrich-stream`, {
    method: 'POST',
    headers: {
      'Authorization': token ? `Bearer ${token}` : '',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ ids }),
    signal: ac.signal,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({} as any))
    enrichDialog.processing = false
    enrichDialog.tables.forEach(t => { t.status = 'error'; t.errorMsg = err.detail || '请求失败' })
    return
  }

  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const resultsMap: Record<string, any> = {}

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      try {
        const event = JSON.parse(line.slice(6))
        const tbl = enrichDialog.tables.find(t => t.id === event.table_id)
        if (!tbl) continue

        if (event.step === 'start') {
          tbl.status = 'processing'
          tbl.collapsed = false
          if (event.message) tbl.logs.push(event.message)
        } else if (event.step === 'saved') {
          tbl.status = 'done'
          tbl.result = event.result
          if (event.message) tbl.logs.push(event.message)
          resultsMap[tbl.id] = event.result
        } else if (event.step === 'error') {
          tbl.status = 'error'
          tbl.errorMsg = event.message
          tbl.collapsed = false
          if (event.message) tbl.logs.push(event.message)
        } else if (event.step === 'all_done') {
          // finished
        } else if (event.step === 'ping') {
          // keep-alive
        } else {
          if (event.message) tbl.logs.push(event.message)
        }
      } catch {}
    }
  }

  enrichAbortController.value = null
  enrichDialog.processing = false

  // Update metadata list with results
  for (const [id, result] of Object.entries(resultsMap)) {
    const idx = metadataList.value.findIndex(m => m.id === id)
    if (idx >= 0) Object.assign(metadataList.value[idx], result)
    rows.forEach(r => { if (r.id === id) Object.assign(r, result) })
  }
  loadStats()

  if (detailData.value) {
    const updated = metadataList.value.find(m => m.id === detailData.value.id)
    if (updated) {
      detailData.value = updated
      Object.assign(editForm, {
        business_name: updated.business_name || '',
        business_description: updated.business_description || '',
        business_tags: updated.business_tags || [],
        business_purpose: updated.business_purpose || '',
        source_system: updated.source_system || '',
        data_domain: updated.data_domain || '',
        security_level: updated.security_level || 'internal',
      })
    }
  }
}

async function loadDatasources() {
  dsLoading.value = true
  try {
    datasources.value = await api.get('/datasources')
    if (datasources.value.length && !filterDataSource.value) {
      selectDataSource(datasources.value[0].id)
    }
  } catch {} finally {
    dsLoading.value = false
  }
}

function selectDataSource(id: string) {
  filterDataSource.value = id
  loadMetadata()
}

async function loadMetadata() {
  loading.value = true
  try {
    const params: any = {}
    if (filterDataSource.value) params.data_source_id = filterDataSource.value
    if (searchQuery.value) params.q = searchQuery.value
    const res = await api.get('/metadata', { params })
    metadataList.value = res.items || []
  } catch (e: any) {
    ElMessage.error(t('metadata.loadFailed'))
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  try {
    stats.value = await api.get('/metadata/stats')
  } catch {}
}

function openDetail(row: any) {
  detailData.value = row
  Object.assign(editForm, {
    business_name: row.business_name || '',
    business_description: row.business_description || '',
    business_tags: row.business_tags || [],
    business_purpose: row.business_purpose || '',
    source_system: row.source_system || '',
    data_domain: row.data_domain || '',
    data_owner: row.data_owner || '',
    security_level: row.security_level || 'internal',
  })
  detailDrawer.value = true
}

async function saveDetail() {
  if (!detailData.value) return
  saving.value = true
  try {
    const res = await api.put(`/metadata/${detailData.value.id}`, editForm)
    Object.assign(detailData.value, res)
    const idx = metadataList.value.findIndex(m => m.id === detailData.value.id)
    if (idx >= 0) Object.assign(metadataList.value[idx], res)
    ElMessage.success(t('metadata.saveSuccess'))
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || t('metadata.saveFailed'))
  } finally {
    saving.value = false
  }
}

async function aiEnrich(row: any) {
  try {
    await ElMessageBox.confirm(
      t('metadata.aiEnrichConfirmMsg'),
      t('metadata.aiEnrichConfirmTitle'),
      { confirmButtonText: t('metadata.startEnrich'), cancelButtonText: t('common.cancel'), type: 'info' }
    )
  } catch {
    return
  }
  enriching.value = true
  row._enriching = true
  try {
    await enrichStreamConcurrent([row])
    if (enrichErrorCount.value > 0) {
      ElMessage.error(t('metadata.aiEnrichFailed'))
    } else {
      ElMessage.success(t('metadata.aiEnrichComplete'))
    }
  } catch (e: any) {
    ElMessage.error(e.message || t('metadata.aiEnrichFailed'))
  } finally {
    enriching.value = false
    row._enriching = false
  }
}

function handleSelectionChange(rows: any[]) {
  selectedRows.value = rows
}

async function batchEnrich() {
  if (!selectedRows.value.length) return
  const count = selectedRows.value.length
  try {
    await ElMessageBox.confirm(
      t('metadata.batchEnrichConfirmMsg', { count }),
      t('metadata.batchEnrichConfirmTitle'),
      { confirmButtonText: t('metadata.startEnrich'), cancelButtonText: t('common.cancel'), type: 'info' }
    )
  } catch {
    return
  }
  batchEnriching.value = true
  const rows = [...selectedRows.value]
  rows.forEach(r => r._enriching = true)
  try {
    await enrichStreamConcurrent(rows)
    if (enrichErrorCount.value > 0) {
      ElMessage.warning(`成功 ${enrichDoneCount.value}，失败 ${enrichErrorCount.value}`)
    } else {
      ElMessage.success(t('metadata.batchEnrichComplete', { success: enrichDoneCount.value }))
    }
  } catch (e: any) {
    ElMessage.error(e.message || t('metadata.enrichFailed'))
  } finally {
    batchEnriching.value = false
    rows.forEach(r => r._enriching = false)
  }
}

async function syncOne(dsId: string) {
  syncing.value = true
  try {
    const res = await api.post(`/metadata/datasources/${dsId}/sync`, {}, { timeout: 120000 })
    ElMessage.success(t('metadata.syncComplete', { count: res.synced }) + (res.deleted_stale ? t('metadata.cleanStaleTables', { count: res.deleted_stale }) : ''))
    await loadMetadata()
    await loadStats()
    if (detailData.value) {
      const updated = metadataList.value.find(m => m.id === detailData.value.id)
      if (updated) detailData.value = updated
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || t('metadata.syncFailed'))
  } finally {
    syncing.value = false
  }
}

function formatNumber(n: any): string {
  if (n == null) return '—'
  if (n >= 10000) return (n / 10000).toFixed(1) + t('metadata.tenThousand')
  return String(n)
}

function formatTime(t: string): string {
  if (!t) return '—'
  return t.replace('T', ' ').substring(0, 16)
}

onMounted(() => {
  loadDatasources()
  loadStats()
})
</script>

<style scoped>
.metadata-page { display: flex; gap: 16px; padding: 16px; }
.ds-sidebar { width: 220px; flex-shrink: 0; background: #fff; border: 1px solid #ebeef5; border-radius: 6px; overflow-y: auto; max-height: calc(100vh - 90px); }
.ds-sidebar-title { padding: 10px 12px; font-weight: 600; font-size: 13px; color: #303133; border-bottom: 1px solid #ebeef5; background: #fafafa; display: flex; align-items: center; justify-content: space-between; }
.ds-item { display: flex; align-items: center; gap: 8px; padding: 9px 12px; cursor: pointer; font-size: 13px; color: #606266; border-bottom: 1px solid #f5f5f5; transition: background 0.15s; }
.ds-item .ds-item-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ds-item:hover { background: #f5f7fa; }
.ds-item.active { background: #ecf5ff; color: #409eff; font-weight: 500; }
.ds-main { flex: 1; min-width: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-header h2 { margin: 0; }
.header-actions { display: flex; gap: 8px; align-items: center; }
.stats-bar { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.table-name { font-weight: 600; }
.table-name-sub { font-size: 12px; color: #909399; }
.text-muted { color: #c0c4cc; font-size: 12px; }
.detail-layout { display: flex; flex-direction: column; gap: 24px; }
.detail-section { }
.section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; font-weight: 600; font-size: 15px; }
.schema-table { margin-top: 12px; }
.sub-title { font-size: 13px; color: #606266; margin-bottom: 8px; }
:deep(.el-table__row) { cursor: pointer; }
:deep(.el-drawer__body) { overflow-y: auto; }

/* AI 增强弹窗 */
.enrich-dialog :deep(.el-dialog__body) {
  max-height: 60vh;
  overflow-y: auto;
}
.enrich-summary {
  display: flex;
  gap: 20px;
  padding: 8px 0 16px;
  border-bottom: 1px solid #ebeef5;
  margin-bottom: 12px;
}
.enrich-summary-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 14px;
  color: #606266;
}
.enrich-table-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.enrich-table-item {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  overflow: hidden;
}
.enrich-table-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: #f5f7fa;
  cursor: pointer;
  user-select: none;
  font-size: 14px;
  transition: background 0.15s;
}
.enrich-table-header:hover {
  background: #ecf0f5;
}
.enrich-table-name {
  flex: 1;
  font-weight: 500;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.enrich-collapse-icon {
  transition: transform 0.3s;
  color: #909399;
}
.enrich-collapse-icon.is-rotated {
  transform: rotate(90deg);
}
.enrich-table-logs {
  padding: 8px 14px 8px 38px;
  background: #fafafa;
  border-top: 1px solid #e4e7ed;
  max-height: 200px;
  overflow-y: auto;
}
.enrich-log-line {
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.7;
  color: #606266;
  white-space: pre-wrap;
  word-break: break-all;
}
.enrich-table-error {
  padding: 8px 14px 8px 38px;
  background: #fef0f0;
  border-top: 1px solid #fde2e2;
  font-size: 13px;
  color: #f56c6c;
  word-break: break-all;
}
.enrich-table-result {
  padding: 6px 14px 8px 38px;
  border-top: 1px solid #e4e7ed;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.enrich-result-tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.is-loading {
  animation: rotating 1.5s linear infinite;
}
</style>
