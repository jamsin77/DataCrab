<template>
  <div class="kb-page">
    <div class="toolbar">
      <el-upload
        :show-file-list="false"
        :http-request="handleUpload"
        accept=".txt,.md,.csv,.json,.xlsx,.xls,.pdf,.docx"
      >
        <el-button type="primary" :loading="uploading">
          <el-icon><Upload /></el-icon> 上传文档
        </el-button>
      </el-upload>
      <el-text size="small" type="info" class="tip">
        支持 txt/md/csv/json/xlsx/pdf/docx，自动切片+嵌入
      </el-text>
      <div class="spacer" />
      <el-input
        v-model="searchQuery"
        placeholder="语义检索知识库..."
        style="width: 300px"
        clearable
        :prefix-icon="Search"
        @keyup.enter="doSearch"
      />
      <el-button type="primary" @click="doSearch" :loading="searching">
        <el-icon><Search /></el-icon> 检索
      </el-button>
    </div>

    <el-tabs v-model="activeTab">
      <el-tab-pane label="文档列表" name="docs">
        <el-table :data="documents" v-loading="loading" stripe>
          <el-table-column label="文档名" min-width="200">
            <template #default="{ row }">
              <el-icon style="vertical-align: middle; margin-right: 4px;"><Document /></el-icon>
              <span>{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="80" prop="file_type" />
          <el-table-column label="大小" width="90" align="right">
            <template #default="{ row }">{{ formatSize(row.size_bytes) }}</template>
          </el-table-column>
          <el-table-column label="切片数" width="80" align="right" prop="chunk_count" />
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag v-if="row.status === 'ready'" type="success" size="small">就绪</el-tag>
              <el-tag v-else-if="row.status === 'processing'" type="warning" size="small">处理中</el-tag>
              <el-tag v-else type="danger" size="small" :title="row.error">失败</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="上传时间" width="160">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="150" align="center">
            <template #default="{ row }">
              <el-button size="small" text type="primary" @click="openChunks(row.id, -1)">查看切片</el-button>
              <el-button size="small" text type="danger" @click="deleteDoc(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!loading && !documents.length" description="暂无文档，上传一个开始构建知识库" />
      </el-tab-pane>

      <el-tab-pane :label="`检索结果${searchResults.length ? ' (' + searchResults.length + ')' : ''}`" name="results">
        <div v-if="!searchResults.length && !searching" class="empty-hint">
          输入自然语言检索，结果带<strong>证据链</strong>：来源文档 + 位置 + 高亮片段，可点击查看上下文。
        </div>
        <div v-for="(r, i) in searchResults" :key="i" class="result-card">
          <div class="result-head">
            <el-icon><Document /></el-icon>
            <span class="doc-name" @click="openChunks(r.document_id, r.chunk_index)">{{ r.doc_name }}</span>
            <el-tag size="small" type="info">{{ r.location }}</el-tag>
            <el-tag v-if="r.score != null" size="small" type="success">相似度 {{ r.score }}</el-tag>
          </div>
          <div class="result-snippet" v-html="highlight(r.content, lastQuery)"></div>
          <el-button text size="small" type="primary" @click="openChunks(r.document_id, r.chunk_index)">
            查看上下文 →
          </el-button>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 切片详情（证据链定位） -->
    <el-drawer v-model="chunksDrawer" :title="chunksDocName" size="55%">
      <div v-loading="chunksLoading">
        <div
          v-for="c in chunks"
          :key="c.id"
          class="chunk-item"
          :class="{ active: c.chunk_index === highlightChunk }"
          :data-idx="c.chunk_index"
        >
          <div class="chunk-head">
            <el-tag size="small">{{ c.location }}</el-tag>
          </div>
          <pre class="chunk-content">{{ c.content }}</pre>
        </div>
        <el-empty v-if="!chunksLoading && !chunks.length" description="暂无切片" />
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload, Document, Search } from '@element-plus/icons-vue'
import { knowledgeApi, type KbDocument, type KbSearchResult } from '@/api/knowledge'

const documents = ref<KbDocument[]>([])
const loading = ref(false)
const uploading = ref(false)

const searchQuery = ref('')
const lastQuery = ref('')
const searching = ref(false)
const searchResults = ref<KbSearchResult[]>([])
const activeTab = ref('docs')

const chunksDrawer = ref(false)
const chunksLoading = ref(false)
const chunks = ref<any[]>([])
const chunksDocName = ref('')
const highlightChunk = ref(-1)

async function loadDocuments() {
  loading.value = true
  try {
    documents.value = await knowledgeApi.listDocuments()
  } catch {
    ElMessage.error('加载文档列表失败')
  } finally {
    loading.value = false
  }
}

async function handleUpload(opt: any) {
  const file = opt.file as File
  uploading.value = true
  try {
    await knowledgeApi.upload(file)
    ElMessage.success(`${file.name} 已导入`)
    await loadDocuments()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '上传失败')
  } finally {
    uploading.value = false
  }
}

async function deleteDoc(row: KbDocument) {
  try {
    await ElMessageBox.confirm(`确定删除「${row.name}」？切片与向量会一并删除。`, '确认删除', { type: 'warning' })
    await knowledgeApi.deleteDocument(row.id)
    ElMessage.success('已删除')
    await loadDocuments()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
}

async function doSearch() {
  const q = searchQuery.value.trim()
  if (!q) return
  searching.value = true
  activeTab.value = 'results'
  searchResults.value = []
  try {
    const res = await knowledgeApi.search(q, 5)
    lastQuery.value = q
    searchResults.value = res.results || []
    if (!searchResults.value.length) ElMessage.info('未检索到相关内容')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '检索失败')
  } finally {
    searching.value = false
  }
}

async function openChunks(docId: string, chunkIdx: number) {
  chunksDrawer.value = true
  chunksLoading.value = true
  chunks.value = []
  highlightChunk.value = chunkIdx
  const doc = documents.value.find(d => d.id === docId)
  chunksDocName.value = doc?.name || '文档切片'
  try {
    chunks.value = await knowledgeApi.getChunks(docId)
    if (chunkIdx >= 0) {
      await nextTick()
      const el = document.querySelector(`.chunk-item[data-idx="${chunkIdx}"]`) as HTMLElement | null
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  } catch {
    ElMessage.error('加载切片失败')
  } finally {
    chunksLoading.value = false
  }
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string))
}

function highlight(content: string, query: string): string {
  const max = 400
  let text = content.length > max ? content.slice(0, max) + '…' : content
  let html = escapeHtml(text)
  const terms = query.split(/\s+/).filter(t => t.length > 1)
  for (const t of terms) {
    const re = new RegExp(escapeHtml(t).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi')
    html = html.replace(re, (m) => `<mark>${m}</mark>`)
  }
  return html
}

function formatSize(bytes: number): string {
  if (!bytes) return '—'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

function formatTime(t: string): string {
  if (!t) return '—'
  return t.replace('T', ' ').substring(0, 16)
}

loadDocuments()
</script>

<style lang="scss" scoped>
.kb-page {
  padding: 20px;
  height: 100%;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;

  .tip { margin-left: 4px; }
  .spacer { flex: 1; }
}

.empty-hint {
  padding: 40px 16px;
  text-align: center;
  color: #909399;
  font-size: 14px;

  strong { color: #606266; }
}

.result-card {
  border: 1px solid #ebeef5;
  border-left: 4px solid #409eff;
  border-radius: 8px;
  padding: 14px 18px;
  margin-bottom: 12px;
  background: #fff;

  .result-head {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;

    .doc-name {
      font-weight: 600;
      color: #303133;
      cursor: pointer;
      &:hover { color: #409eff; text-decoration: underline; }
    }
  }

  .result-snippet {
    font-size: 13.5px;
    line-height: 1.7;
    color: #606266;
    margin-bottom: 6px;

    :deep(mark) {
      background: #fff3a0;
      color: #7a5a00;
      padding: 0 2px;
      border-radius: 2px;
    }
  }
}

.chunk-item {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 10px;
  background: #fff;
  scroll-margin-top: 80px;

  &.active {
    border-color: #409eff;
    box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.15);
    background: #f5faff;
  }

  .chunk-head {
    margin-bottom: 6px;
  }

  .chunk-content {
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
    font-family: 'Consolas', 'Monaco', monospace;
    font-size: 12.5px;
    line-height: 1.6;
    color: #303133;
    background: #ffffff;
    border: 1px solid #ebeef5;
    border-radius: 6px;
    padding: 10px;
    max-height: 240px;
    overflow-y: auto;
  }
}
</style>
