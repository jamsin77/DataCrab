<template>
  <div class="standards-config">
    <el-tabs v-model="subTab">
      <el-tab-pane :label="t('config.standards.standards')" name="standards">
        <div class="editor-toolbar">
          <span class="toolbar-hint">{{ t('config.standards.standardsHint') }}</span>
          <div class="toolbar-btns">
            <el-button size="small" @click="load('standards')" :loading="loading.standards">{{ t('config.standards.reload') }}</el-button>
            <el-button size="small" type="warning" plain @click="reset('standards')" :loading="resetting.standards">{{ t('config.standards.resetToDefault') }}</el-button>
            <el-button size="small" type="primary" @click="save('standards')" :loading="saving.standards">{{ t('config.standards.save') }}</el-button>
          </div>
        </div>
        <el-input
          v-model="content.standards"
          type="textarea"
          :autosize="{ minRows: 10, maxRows: 20 }"
          class="md-editor"
          :placeholder="t('config.standards.standardsPlaceholder')"
        />
      </el-tab-pane>

      <el-tab-pane :label="t('config.standards.quality')" name="quality">
        <div class="editor-toolbar">
          <span class="toolbar-hint">{{ t('config.standards.qualityHint') }}</span>
          <div class="toolbar-btns">
            <el-button size="small" @click="load('quality')" :loading="loading.quality">{{ t('config.standards.reload') }}</el-button>
            <el-button size="small" type="warning" plain @click="reset('quality')" :loading="resetting.quality">{{ t('config.standards.resetToDefault') }}</el-button>
            <el-button size="small" type="primary" @click="save('quality')" :loading="saving.quality">{{ t('config.standards.save') }}</el-button>
          </div>
        </div>
        <el-input
          v-model="content.quality"
          type="textarea"
          :autosize="{ minRows: 10, maxRows: 20 }"
          class="md-editor"
          :placeholder="t('config.standards.qualityPlaceholder')"
        />
      </el-tab-pane>

      <el-tab-pane :label="t('config.standards.security')" name="security">
        <div class="editor-toolbar">
          <span class="toolbar-hint">{{ t('config.standards.securityHint') }}</span>
          <div class="toolbar-btns">
            <el-button size="small" @click="load('security')" :loading="loading.security">{{ t('config.standards.reload') }}</el-button>
            <el-button size="small" type="warning" plain @click="reset('security')" :loading="resetting.security">{{ t('config.standards.resetToDefault') }}</el-button>
            <el-button size="small" type="primary" @click="save('security')" :loading="saving.security">{{ t('config.standards.save') }}</el-button>
          </div>
        </div>
        <el-input
          v-model="content.security"
          type="textarea"
          :autosize="{ minRows: 10, maxRows: 20 }"
          class="md-editor"
          :placeholder="t('config.standards.securityPlaceholder')"
        />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import api from '@/api/index'

const { t } = useI18n()
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
    ElMessage.error(e.response?.data?.detail || t('config.standards.loadFailed'))
  } finally {
    loading[key] = false
  }
}

async function save(key: Key) {
  saving[key] = true
  try {
    await api.put(pathMap[key], { content: content[key] })
    ElMessage.success(t('config.standards.saveSuccess'))
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || t('config.standards.saveFailed'))
  } finally {
    saving[key] = false
  }
}

async function reset(key: Key) {
  resetting[key] = true
  try {
    await api.post(`${pathMap[key]}/reset`)
    await load(key)
    ElMessage.success(t('config.standards.resetSuccess'))
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || t('config.standards.resetFailed'))
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
