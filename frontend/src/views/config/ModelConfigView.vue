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

        <el-form-item label="默认模型">
          <el-select v-model="form.model" placeholder="选择默认模型" style="width: 100%" @change="clearAlerts">
            <el-option
              v-for="m in availableModels"
              :key="m.value"
              :label="m.label"
              :value="m.value"
            />
          </el-select>
          <div class="form-tip">
            <el-text size="small" type="info">
              对话、调试、分析等场景默认使用的模型
            </el-text>
          </div>
        </el-form-item>

        <el-form-item label="快速模型">
          <el-select v-model="form.flash_model" placeholder="选择快速模型" style="width: 100%" @change="clearAlerts">
            <el-option
              v-for="m in availableModels"
              :key="m.value"
              :label="m.label"
              :value="m.value"
            />
          </el-select>
          <div class="form-tip">
            <el-text size="small" type="info">
              数据检查、参数推断等简单任务使用的轻量模型，留空则按 Provider 推荐或回退默认模型
            </el-text>
          </div>
        </el-form-item>

        <el-form-item label="视觉模型">
          <el-select
            v-model="form.vision_model"
            placeholder="留空表示不支持图片识别"
            style="width: 100%"
            filterable
            allow-create
            clearable
            default-first-option
            @change="clearAlerts"
          >
            <el-option
              v-for="m in visionModelOptions"
              :key="m.value"
              :label="m.label"
              :value="m.value"
            />
          </el-select>
          <div class="form-tip">
            <el-text size="small" type="info">
              OCR/图片识别使用的模型，留空则不支持视觉任务
            </el-text>
          </div>
        </el-form-item>

        <el-form-item label="向量模型">
          <el-select
            v-model="form.embedding_model"
            placeholder="留空表示不支持向量化"
            style="width: 100%"
            filterable
            allow-create
            clearable
            default-first-option
            @change="clearAlerts"
          >
            <el-option
              v-for="m in embeddingModelOptions"
              :key="m.value"
              :label="m.label"
              :value="m.value"
            />
          </el-select>
          <div class="form-tip">
            <el-text size="small" type="info">
              知识库向量化使用的模型，留空则不支持向量化
            </el-text>
          </div>
        </el-form-item>

        <el-divider content-position="left">备用模型（主模型不可用时自动降级）</el-divider>

        <div v-for="(fb, idx) in fallbackModels" :key="idx" class="fallback-item">
          <div class="fallback-header">
            <span class="fallback-title">备用 {{ idx + 1 }}</span>
            <el-button type="danger" circle size="small" @click="fallbackModels.splice(idx, 1)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
          <el-form-item label="提供商">
            <el-select v-model="fb.provider" placeholder="选择提供商" style="width: 100%" filterable @change="onFallbackProviderChange(fb)">
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
                v-model="fb.api_key"
                type="password"
                show-password
                style="flex: 1"
                :placeholder="fb.api_key_set ? '已设置（输入可更新）' : '请输入API Key'"
              />
              <el-tag v-if="fb.api_key_set" type="success" size="small">已配置</el-tag>
            </div>
          </el-form-item>
          <el-form-item label="API 地址">
            <el-input v-model="fb.api_base" placeholder="留空用默认" />
          </el-form-item>
          <el-form-item label="默认模型">
            <el-select v-model="fb.model" placeholder="选择默认模型" style="width: 100%" filterable allow-create clearable default-first-option>
              <el-option v-for="m in (getProviderModels(fb.provider) || [])" :key="m.value" :label="m.label" :value="m.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="快速模型">
            <el-select v-model="fb.flash_model" placeholder="留空用默认" style="width: 100%" filterable allow-create clearable default-first-option>
              <el-option v-for="m in (getProviderModels(fb.provider) || [])" :key="m.value" :label="m.label" :value="m.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="视觉模型">
            <el-select v-model="fb.vision_model" placeholder="留空不支持" style="width: 100%" filterable allow-create clearable default-first-option>
              <el-option v-for="m in (getProviderModels(fb.provider) || [])" :key="m.value" :label="m.label" :value="m.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="向量模型">
            <el-select v-model="fb.embedding_model" placeholder="留空不支持" style="width: 100%" filterable allow-create clearable default-first-option>
              <el-option v-for="m in (getProviderModels(fb.provider) || [])" :key="m.value" :label="m.label" :value="m.value" />
            </el-select>
          </el-form-item>
        </div>
        <el-button type="primary" plain size="small" @click="addFallback" style="margin-bottom: 16px">
          <el-icon><Plus /></el-icon> 添加备用模型
        </el-button>

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
        :title="testResult.success ? '连接测试通过' : '连接测试存在问题'"
        :type="testResult.success ? 'success' : 'warning'"
        :description="testResult.message"
        show-icon
        closable
        @close="testResult = null"
        style="margin-top: 16px"
      />

      <div v-if="testResult?.results?.length" class="test-results">
        <div
          v-for="(r, idx) in testResult.results"
          :key="idx"
          class="test-result-item"
        >
          <el-tag :type="r.success ? 'success' : 'danger'" size="small">
            {{ r.success ? '✓ 成功' : '✗ 失败' }}
          </el-tag>
          <span class="test-result-label">{{ r.label }}</span>
          <span class="test-result-model">{{ r.provider }} / {{ r.model || '未设置' }}</span>
          <span class="test-result-msg" :class="{ 'err': !r.success }">{{ r.message }}</span>
        </div>
      </div>

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
          主模型不可用时（如 API 故障、限流），自动降级到备用模型。图片识别和向量化由平台按 Provider 自动选择。
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
import { Delete, Plus } from '@element-plus/icons-vue'

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)

const providers = ref<any[]>([])

function getProviderApiBase(providerName: string): string {
  const p = providers.value.find(p => p.provider_name === providerName)
  return p?.api_base || ''
}

function getProviderModels(providerName: string): any[] {
  const p = providers.value.find(p => p.provider_name === providerName)
  return p?.models || []
}

function getProviderDefaultModel(providerName: string): string {
  const p = providers.value.find(p => p.provider_name === providerName)
  return p?.default_model || ''
}

function getProviderDefaultFlashModel(providerName: string): string {
  const p = providers.value.find(p => p.provider_name === providerName)
  return p?.flash_model || ''
}

function getProviderDefaultVisionModel(providerName: string): string {
  const p = providers.value.find(p => p.provider_name === providerName)
  return p?.vision_model || ''
}

function getProviderDefaultEmbeddingModel(providerName: string): string {
  const p = providers.value.find(p => p.provider_name === providerName)
  return p?.embedding_model || ''
}

const availableModels = computed(() => getProviderModels(form.value.provider))

const apiBasePlaceholder = computed(() => getProviderApiBase(form.value.provider) || '请填写 API 地址')

const visionModelOptions = computed(() => getProviderModels(form.value.provider))

const embeddingModelOptions = computed(() => getProviderModels(form.value.provider))

function formatCapabilities(row: any): string {
  const caps = []
  if (row.default_model) caps.push('深度')
  if (row.vision_model) caps.push('视觉')
  if (row.embedding_model) caps.push('向量')
  if (row.models && row.models.length > 0) caps.push('文本')
  return caps.join('/') || '-'
}

function onProviderChange() {
  clearAlerts()
  form.value.api_base = getProviderApiBase(form.value.provider) || ''
  form.value.model = getProviderDefaultModel(form.value.provider) || ''
  form.value.flash_model = getProviderDefaultFlashModel(form.value.provider) || ''
  form.value.vision_model = getProviderDefaultVisionModel(form.value.provider) || ''
  form.value.embedding_model = getProviderDefaultEmbeddingModel(form.value.provider) || ''
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
  flash_model: '',
  vision_model: '',
  embedding_model: '',
})

const fallbackModels = ref<any[]>(([]))

function addFallback() {
  fallbackModels.value.push({ provider: '', model: '', flash_model: '', vision_model: '', embedding_model: '', api_key: '', api_key_set: false, api_base: '' })
}

function onFallbackProviderChange(fb: any) {
  fb.model = getProviderDefaultModel(fb.provider) || ''
  fb.flash_model = getProviderDefaultFlashModel(fb.provider) || ''
  fb.vision_model = getProviderDefaultVisionModel(fb.provider) || ''
  fb.embedding_model = getProviderDefaultEmbeddingModel(fb.provider) || ''
  if (!fb.api_base) {
    fb.api_base = getProviderApiBase(fb.provider) || ''
  }
}

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
      flash_model: res.flash_model || '',
      vision_model: res.vision_model || '',
      embedding_model: res.embedding_model || '',
    }
    fallbackModels.value = (res.fallback_models || []).map((f: any) => ({
      provider: f.provider || '',
      model: f.model || '',
      flash_model: f.flash_model || '',
      vision_model: f.vision_model || '',
      embedding_model: f.embedding_model || '',
      api_key: '',
      api_key_set: f.api_key_set || false,
      api_base: f.api_base || '',
    }))
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
    const payload: any = {
      provider: form.value.provider,
      api_key: form.value.api_key,
      api_base: form.value.api_base,
      model: form.value.model,
      flash_model: form.value.flash_model || '',
      vision_model: form.value.vision_model || '',
      embedding_model: form.value.embedding_model || '',
    }
    // 只发送有 provider 的备用模型
    const validFallbacks = fallbackModels.value.filter(f => f.provider)
    if (validFallbacks.length > 0) {
      payload.fallback_models = validFallbacks.map(f => ({
        provider: f.provider,
        model: f.model,
        flash_model: f.flash_model || '',
        vision_model: f.vision_model || '',
        embedding_model: f.embedding_model || '',
        api_key: f.api_key || undefined,
        api_base: f.api_base,
      }))
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
    const validFallbacks = fallbackModels.value.filter(f => f.provider)
    const res = await api.post('/config/llm/test', {
      provider: form.value.provider,
      api_key: form.value.api_key || undefined,
      api_base: form.value.api_base || undefined,
      model: form.value.model || undefined,
      fallback_models: validFallbacks.map(f => ({
        provider: f.provider,
        model: f.model,
        api_key: f.api_key || undefined,
        api_base: f.api_base || undefined,
      })),
    })
    testResult.value = res
    if (res.success) {
      ElMessage.success('全部连接测试成功')
    } else if (res.results?.length > 1) {
      ElMessage.warning(res.message)
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

.fallback-item {
  padding: 12px 16px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  margin-bottom: 12px;
  background: #fafafa;

  .fallback-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;

    .fallback-title {
      font-weight: 600;
      color: #303133;
    }
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

.test-results {
  margin-top: 12px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  overflow: hidden;

  .test-result-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    border-bottom: 1px solid #f0f0f0;
    font-size: 13px;

    &:last-child {
      border-bottom: none;
    }

    .test-result-label {
      font-weight: 500;
      min-width: 60px;
    }

    .test-result-model {
      color: #909399;
      min-width: 200px;
    }

    .test-result-msg {
      color: #67c23a;

      &.err {
        color: #f56c6c;
      }
    }
  }
}
</style>
