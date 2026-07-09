<template>
  <div class="metadata-page">
    <!-- 左侧：按数据源浏览 -->
    <div class="ds-sidebar">
      <div class="ds-sidebar-title">
        <span>数据源</span>
        <el-button size="small" text :loading="dsLoading" @click="loadDatasources">
          <el-icon><Refresh /></el-icon>
        </el-button>
      </div>
      <div class="ds-item" :class="{ active: !filterDataSource }" @click="selectDataSource('')">
        <el-icon><Files /></el-icon>
        <span>全部数据源</span>
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
      <el-empty v-if="!datasources.length" description="暂无数据源" :image-size="50" />
    </div>

    <!-- 右侧：表格与搜索 -->
    <div class="ds-main">
      <div class="page-header">
        <h2>元数据管理</h2>
        <div class="header-actions">
          <el-input v-model="searchQuery" placeholder="搜索表名/业务名称/描述..." clearable style="width: 280px" @clear="loadMetadata" @keyup.enter="loadMetadata">
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-button type="primary" @click="loadMetadata">刷新</el-button>
        </div>
      </div>

    <div class="stats-bar" v-if="stats">
      <el-tag type="info">总计 {{ stats.total }} 个数据集</el-tag>
      <el-tag type="success">AI补充 {{ stats.ai_enriched }} 个</el-tag>
      <el-tag v-for="(count, fmt) in stats.by_format" :key="fmt" type="warning">{{ fmt }}: {{ count }}</el-tag>
    </div>

    <el-table :data="metadataList" v-loading="loading" style="width: 100%" @row-click="openDetail">
      <el-table-column label="数据集名称" min-width="160">
        <template #default="{ row }">
          <span class="table-name">{{ row.business_name || row.table_name }}</span>
          <div class="table-name-sub">{{ row.table_name }}</div>
        </template>
      </el-table-column>
      <el-table-column label="数据源" width="120" prop="data_source_name" />
      <el-table-column label="格式" width="80" prop="storage_format" />
      <el-table-column label="行数" width="90" align="right">
        <template #default="{ row }">{{ formatNumber(row.row_count) }}</template>
      </el-table-column>
      <el-table-column label="列数" width="70" align="right" prop="column_count" />
      <el-table-column label="业务标签" min-width="160">
        <template #default="{ row }">
          <el-tag v-for="tag in (row.business_tags || [])" :key="tag" size="small" style="margin-right: 4px">{{ tag }}</el-tag>
          <span v-if="!row.business_tags?.length" class="text-muted">未设置</span>
        </template>
      </el-table-column>
      <el-table-column label="AI" width="50" align="center">
        <template #default="{ row }">
          <el-icon v-if="row.ai_enriched" color="#67c23a"><CircleCheckFilled /></el-icon>
        </template>
      </el-table-column>
      <el-table-column label="同步时间" width="150">
        <template #default="{ row }">{{ formatTime(row.last_synced_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="120" align="center">
        <template #default="{ row }">
          <el-button size="small" text type="primary" @click.stop="openDetail(row)">详情</el-button>
          <el-button size="small" text type="success" @click.stop="aiEnrich(row)" :loading="row._enriching">AI补充</el-button>
        </template>
      </el-table-column>
    </el-table>
    </div>

    <el-drawer v-model="detailDrawer" :title="detailData?.business_name || detailData?.table_name || '元数据详情'" size="60%">
      <div v-if="detailData" class="detail-layout">
        <div class="detail-section">
          <div class="section-header">
            <span>技术元数据</span>
            <el-button size="small" type="primary" plain @click="syncOne(detailData.data_source_id)" :loading="syncing">重新同步</el-button>
          </div>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="数据集名称">{{ detailData.table_name }}</el-descriptions-item>
            <el-descriptions-item label="业务名称">{{ detailData.business_name || '—' }}</el-descriptions-item>
            <el-descriptions-item label="类型">{{ detailData.table_type || '—' }}</el-descriptions-item>
            <el-descriptions-item label="格式">{{ detailData.storage_format || '—' }}</el-descriptions-item>
            <el-descriptions-item label="存放地址" :span="2"><code>{{ detailData.storage_location || '—' }}</code></el-descriptions-item>
            <el-descriptions-item label="行数">{{ formatNumber(detailData.row_count) }}</el-descriptions-item>
            <el-descriptions-item label="列数">{{ detailData.column_count }}</el-descriptions-item>
          </el-descriptions>

          <div v-if="detailData.table_schema?.length" class="schema-table">
            <div class="sub-title">字段定义</div>
            <el-table :data="detailData.table_schema" size="small" border>
              <el-table-column label="列名" prop="name" min-width="120" />
              <el-table-column label="类型" prop="dtype" width="120" />
              <el-table-column label="可空" width="60" align="center">
                <template #default="{ row }">{{ row.nullable ? '是' : '否' }}</template>
              </el-table-column>
            </el-table>
          </div>

          <el-collapse v-if="detailData.sample_data?.length" style="margin-top: 12px">
            <el-collapse-item title="样本数据（前5行）">
              <pre>{{ JSON.stringify(detailData.sample_data, null, 2) }}</pre>
            </el-collapse-item>
          </el-collapse>
        </div>

        <div class="detail-section">
          <div class="section-header">
            <span>业务元数据</span>
            <el-button size="small" type="success" @click="aiEnrich(detailData)" :loading="enriching">AI补充</el-button>
          </div>
          <el-form label-width="100px">
            <el-form-item label="业务名称">
              <el-input v-model="editForm.business_name" placeholder="数据集的业务名称" />
            </el-form-item>
            <el-form-item label="业务描述">
              <el-input v-model="editForm.business_description" type="textarea" :rows="2" />
            </el-form-item>
            <el-form-item label="业务标签">
              <el-select v-model="editForm.business_tags" multiple filterable allow-create default-first-option style="width: 100%" placeholder="添加标签">
              </el-select>
            </el-form-item>
            <el-form-item label="业务用途">
              <el-input v-model="editForm.business_purpose" type="textarea" :rows="2" />
            </el-form-item>
            <el-form-item label="来源系统">
              <el-input v-model="editForm.source_system" />
            </el-form-item>
            <el-form-item label="数据域">
              <el-input v-model="editForm.data_domain" />
            </el-form-item>
            <el-form-item label="数据所有者">
              <el-input v-model="editForm.data_owner" />
            </el-form-item>
            <el-form-item label="安全等级">
              <el-select v-model="editForm.security_level" style="width: 100%">
                <el-option label="公开" value="public" />
                <el-option label="内部" value="internal" />
                <el-option label="机密" value="confidential" />
                <el-option label="绝密" value="secret" />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="saveDetail" :loading="saving">保存修改</el-button>
            </el-form-item>
          </el-form>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { Search, CircleCheckFilled, Files, Connection, Refresh } from '@element-plus/icons-vue'
import api from '@/api/index'
import { ElMessage } from 'element-plus'

const loading = ref(false)
const metadataList = ref<any[]>([])
const datasources = ref<any[]>([])
const filterDataSource = ref('')
const searchQuery = ref('')
const stats = ref<any>(null)

const detailDrawer = ref(false)
const detailData = ref<any>(null)
const editForm = reactive<any>({})
const saving = ref(false)
const enriching = ref(false)
const syncing = ref(false)
const dsLoading = ref(false)

async function loadDatasources() {
  dsLoading.value = true
  try {
    datasources.value = await api.get('/datasources')
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
    ElMessage.error('加载失败')
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
    ElMessage.success('保存成功')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function aiEnrich(row: any) {
  enriching.value = true
  row._enriching = true
  try {
    const res = await api.post(`/metadata/${row.id}/ai-enrich`, {}, { timeout: 120000 })
    Object.assign(row, res)
    if (detailData.value?.id === row.id) {
      detailData.value = res
      Object.assign(editForm, {
        business_name: res.business_name || '',
        business_description: res.business_description || '',
        business_tags: res.business_tags || [],
        business_purpose: res.business_purpose || '',
        source_system: res.source_system || '',
        data_domain: res.data_domain || '',
        security_level: res.security_level || 'internal',
      })
    }
    const idx = metadataList.value.findIndex(m => m.id === row.id)
    if (idx >= 0) Object.assign(metadataList.value[idx], res)
    ElMessage.success('AI补充完成')
    loadStats()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || 'AI补充失败')
  } finally {
    enriching.value = false
    row._enriching = false
  }
}

async function syncOne(dsId: string) {
  syncing.value = true
  try {
    const res = await api.post(`/metadata/datasources/${dsId}/sync`, {}, { timeout: 120000 })
    ElMessage.success(`同步完成: ${res.synced} 张表`)
    await loadMetadata()
    await loadStats()
    if (detailData.value) {
      const updated = metadataList.value.find(m => m.id === detailData.value.id)
      if (updated) detailData.value = updated
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '同步失败')
  } finally {
    syncing.value = false
  }
}

function formatNumber(n: any): string {
  if (n == null) return '—'
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  return String(n)
}

function formatTime(t: string): string {
  if (!t) return '—'
  return t.replace('T', ' ').substring(0, 16)
}

onMounted(() => {
  loadDatasources()
  loadMetadata()
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
</style>
