<template>
  <div class="model-config-container">
    <el-card class="config-card">
      <template #header>
        <div class="card-header">
          <span>大模型配置</span>
          <el-tag :type="config.is_configured ? 'success' : 'warning'">
            {{ config.is_configured ? '已配置' : '未配置' }}
          </el-tag>
        </div>
      </template>

      <el-form :model="form" label-width="120px" v-loading="loading">
        <el-form-item label="服务提供商">
          <el-select v-model="form.provider" placeholder="选择提供商" @change="onProviderChange">
            <el-option
              v-for="p in providers"
              :key="p.provider_name"
              :label="p.display_name"
              :value="p.provider_name"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="API Key">
          <div style="display: flex; align-items: center; gap: 8px; width: 100%;">
            <el-input
              v-model="form.api_key"
              type="password"
              show-password
              style="flex: 1"
              :placeholder="config.api_key_set ? '已设置（输入可更新）' : '请输入API Key'"
              @input="clearAlerts"
            />
            <el-tag v-if="config.api_key_set" type="success" size="small">已配置</el-tag>
          </div>
          <div class="form-tip">
            <el-text size="small" type="info">
              API密钥用于调用大模型服务，请妥善保管
            </el-text>
          </div>
        </el-form-item>

        <el-form-item label="API 地址">
          <el-input
            v-model="form.api_base"
            :placeholder="apiBasePlaceholder"
            @input="clearAlerts"
          />
          <div class="form-tip">
            <el-text size="small" type="info">
              {{ form.provider === 'custom' ? '可填写自定义API地址，如 http://localhost:8000/v1' : '已自动填入官方地址，如需代理可修改' }}
            </el-text>
          </div>
        </el-form-item>

        <el-form-item label="深度模型">
          <el-input
            v-model="form.model"
            placeholder="用于复杂推理，如 glm-5.2"
            @input="clearAlerts"
          />
          <div class="form-tip">
            <el-text size="small" type="info">用于数据分析、脚本生成/调试等深度推理任务</el-text>
          </div>
        </el-form-item>

        <el-form-item label="快速模型">
          <el-input
            v-model="form.fast_model"
            placeholder="用于简单任务，如 glm-4-flash"
            @input="clearAlerts"
          />
          <div class="form-tip">
            <el-text size="small" type="info">用于参数推断、简单对话等快速响应任务（留空则用深度模型）</el-text>
          </div>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="saveConfig" :loading="saving">
            保存配置
          </el-button>
          <el-button @click="testConnection" :loading="testing">
            测试连接
          </el-button>
          <el-button @click="loadConfig">
            刷新
          </el-button>
        </el-form-item>
      </el-form>

      <el-alert
        v-if="testResult"
        :title="testResult.success ? '连接成功' : '连接失败'"
        :type="testResult.success ? 'success' : 'error'"
        :description="testResult.message"
        show-icon
        closable
        @close="testResult = null"
        style="margin-top: 16px"
      />

      <el-alert
        v-if="saveResult"
        :title="saveResult.success ? '保存成功' : '保存失败'"
        :type="saveResult.success ? 'success' : 'error'"
        :description="saveResult.message"
        show-icon
        closable
        @close="saveResult = null"
        style="margin-top: 16px"
      />
    </el-card>

    <el-card class="help-card" style="margin-top: 16px">
      <template #header>
        <span>使用说明</span>
      </template>
      <div class="help-content">
        <h4>配置步骤</h4>
        <ol>
          <li>选择服务提供商</li>
          <li>输入对应的API Key</li>
          <li>如使用自定义服务，填写API地址</li>
          <li>点击"测试连接"验证配置</li>
          <li>点击"保存配置"保存设置</li>
        </ol>
        <el-text size="small" type="info">
          深度模型用于复杂推理，快速模型用于简单任务。图片识别和向量化由平台按 Provider 自动选择。
        </el-text>

        <h4 style="margin-top: 16px">已注册的 Provider</h4>
        <el-table :data="providerTableData" size="small">
          <el-table-column prop="display_name" label="名称" />
          <el-table-column prop="provider_name" label="标识" />
          <el-table-column prop="api_base" label="API 地址" show-overflow-tooltip />
          <el-table-column label="支持能力" show-overflow-tooltip>
            <template #default="{ row }">
              {{ formatCapabilities(row) }}
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import api from '@/api/index'
import { ElMessage } from 'element-plus'

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)

const providers = ref<any[]>([])

function getProviderApiBase(providerName: string): string {
  const p = providers.value.find(p => p.provider_name === providerName)
  return p?.api_base || ''
}

const apiBasePlaceholder = computed(() => getProviderApiBase(form.value.provider) || '请填写 API 地址')

function formatCapabilities(row: any): string {
  const caps = []
  if (row.default_model) caps.push('深度')
  if (row.fast_model) caps.push('快速')
  if (row.models && row.models.length > 0) caps.push('文本')
  return caps.join('/') || '-'
}

function onProviderChange() {
  clearAlerts()
  form.value.api_base = getProviderApiBase(form.value.provider) || ''
}

const config = ref({
  provider: 'glm',
  api_key_set: false,
  api_base: '',
  is_configured: false
})

const form = ref({
  provider: 'glm',
  api_key: '',
  api_base: '',
  model: '',
  fast_model: '',
})

const testResult = ref<any>(null)
const saveResult = ref<any>(null)

function clearAlerts() {
  testResult.value = null
  saveResult.value = null
}

const providerTableData = computed(() => providers.value)

onMounted(async () => {
  await loadProviders()
  await loadConfig()
})

async function loadProviders() {
  try {
    providers.value = await api.get('/providers')
  } catch {}
}

async function loadConfig(preserveApiKey = false) {
  loading.value = true
  clearAlerts()
  try {
    const res = await api.get('/config/llm')
    config.value = res
    const currentApiKey = preserveApiKey ? form.value.api_key : ''
    form.value = {
      provider: res.provider,
      api_key: res.api_key_set ? '' : currentApiKey,
      api_base: res.api_base || '',
      model: res.model || '',
      fast_model: res.fast_model || '',
    }
  } catch (e: any) {
    ElMessage.error('加载配置失败')
  } finally {
    loading.value = false
  }
}

async function saveConfig() {
  saving.value = true
  saveResult.value = null
  const hasNewApiKey = form.value.api_key && form.value.api_key.trim() !== ''
  try {
    const payload = {
      provider: form.value.provider,
      api_key: form.value.api_key,
      api_base: form.value.api_base,
      model: form.value.model,
      fast_model: form.value.fast_model,
    }
    const res = await api.post('/config/llm', payload)
    saveResult.value = res
    if (res.success) {
      ElMessage.success('配置已保存')
      config.value = {
        ...config.value,
        api_key_set: hasNewApiKey || config.value.api_key_set,
        is_configured: hasNewApiKey || config.value.is_configured,
      }
      if (!hasNewApiKey) {
        form.value.api_key = ''
      }
    }
  } catch (e: any) {
    saveResult.value = { success: false, message: e.response?.data?.detail || '保存失败' }
  } finally {
    saving.value = false
  }
}

async function testConnection() {
  testing.value = true
  testResult.value = null
  try {
    const res = await api.post('/config/llm/test', {
      provider: form.value.provider,
      api_key: form.value.api_key || undefined,
      api_base: form.value.api_base || undefined,
      model: form.value.model || undefined,
    })
    testResult.value = res
    if (res.success) {
      ElMessage.success('连接测试成功')
    } else {
      ElMessage.warning('连接测试失败')
    }
  } catch (e: any) {
    testResult.value = { success: false, message: e.response?.data?.detail || '测试失败' }
  } finally {
    testing.value = false
  }
}
</script>

<style lang="scss" scoped>
.model-config-container {
  max-width: 800px;
}

.config-card {
  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
}

.form-tip {
  margin-top: 4px;
}

.help-card {
  .help-content {
    h4 {
      margin: 12px 0 8px;
      color: #303133;
    }
    ol {
      margin-left: 20px;
      color: #606266;
    }
  }
}
</style>
