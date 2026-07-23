<template>
  <div class="standards-config">
    <el-tabs v-model="subTab">
      <el-tab-pane label="数据标准规则" name="standards">
        <div class="editor-toolbar">
          <span class="toolbar-hint">字段级数据格式与约束标准（DataInspector 检查时引用 STD-xxx）</span>
          <div class="toolbar-btns">
            <el-button size="small" @click="load('standards')" :loading="loading.standards">重新加载</el-button>
            <el-button size="small" type="warning" plain @click="reset('standards')" :loading="resetting.standards">恢复默认</el-button>
            <el-button size="small" type="primary" @click="save('standards')" :loading="saving.standards">保存</el-button>
          </div>
        </div>
        <el-input
          v-model="content.standards"
          type="textarea"
          :autosize="{ minRows: 10, maxRows: 20 }"
          class="md-editor"
          :placeholder="'加载数据标准库...'"
        />
      </el-tab-pane>

      <el-tab-pane label="数据质量规则" name="quality">
        <div class="editor-toolbar">
          <span class="toolbar-hint">规则级数据质量检查规则（DataInspector 检查时引用 DQ-xxx）</span>
          <div class="toolbar-btns">
            <el-button size="small" @click="load('quality')" :loading="loading.quality">重新加载</el-button>
            <el-button size="small" type="warning" plain @click="reset('quality')" :loading="resetting.quality">恢复默认</el-button>
            <el-button size="small" type="primary" @click="save('quality')" :loading="saving.quality">保存</el-button>
          </div>
        </div>
        <el-input
          v-model="content.quality"
          type="textarea"
          :autosize="{ minRows: 10, maxRows: 20 }"
          class="md-editor"
          :placeholder="'加载数据质量库...'"
        />
      </el-tab-pane>

      <el-tab-pane label="数据安全规则" name="security">
        <div class="editor-toolbar">
          <span class="toolbar-hint">数据安全检查规则（DataInspector 检查时引用 SEC-xxx）</span>
          <div class="toolbar-btns">
            <el-button size="small" @click="load('security')" :loading="loading.security">重新加载</el-button>
            <el-button size="small" type="warning" plain @click="reset('security')" :loading="resetting.security">恢复默认</el-button>
            <el-button size="small" type="primary" @click="save('security')" :loading="saving.security">保存</el-button>
          </div>
        </div>
        <el-input
          v-model="content.security"
          type="textarea"
          :autosize="{ minRows: 10, maxRows: 20 }"
          class="md-editor"
          :placeholder="'加载数据安全规则库...'"
        />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/api/index'

const subTab = ref('standards')
const content = reactive<{ standards: string; quality: string; security: string }>({ standards: '', quality: '', security: '' })
const loading = reactive({ standards: false, quality: false, security: false })
const saving = reactive({ standards: false, quality: false, security: false })
const resetting = reactive({ standards: false, quality: false, security: false })

const pathMap = {
  standards: '/config/data-standards',
  quality: '/config/data-quality',
  security: '/config/data-security',
} as const

type Key = keyof typeof pathMap

async function load(key: Key) {
  loading[key] = true
  try {
    const res = await api.get(pathMap[key])
    content[key] = (res && (res as any).content) || ''
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载失败')
  } finally {
    loading[key] = false
  }
}

async function save(key: Key) {
  saving[key] = true
  try {
    await api.put(pathMap[key], { content: content[key] })
    ElMessage.success('已保存')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving[key] = false
  }
}

async function reset(key: Key) {
  resetting[key] = true
  try {
    await api.post(`${pathMap[key]}/reset`)
    await load(key)
    ElMessage.success('已恢复默认')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '恢复失败')
  } finally {
    resetting[key] = false
  }
}

onMounted(() => {
  load('standards')
  load('quality')
  load('security')
})
</script>

<style lang="scss" scoped>
.standards-config {
  .editor-toolbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;

    .toolbar-hint {
      font-size: 13px;
      color: #909399;
    }
    .toolbar-btns {
      display: flex;
      gap: 8px;
    }
  }

  .md-editor {
    :deep(.el-textarea__inner) {
      font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
      font-size: 13px;
      line-height: 1.6;
      white-space: pre-wrap;
      word-break: break-word;
      max-height: calc(100vh - 280px);
      overflow-y: auto;
    }
  }
}
</style>
