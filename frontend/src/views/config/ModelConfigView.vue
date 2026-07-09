<template>
  <div class="model-config-container">
    <el-card class="config-card">
      <template #header>
        <div class="card-header">
          <span>LLM 模型配置</span>
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
          <el-select v-model="form.model" placeholder="选择模型" filterable allow-create @change="clearAlerts">
            <el-option
              v-for="m in availableModels"
              :key="m.value"
              :label="m.label"
              :value="m.value"
            />
          </el-select>
          <div class="form-tip">
            <el-text size="small" type="info">
              深度推理模型，用于生成/修改脚本、流程生成等需要深度思考的场景
            </el-text>
          </div>
        </el-form-item>

        <el-form-item label="快速模型">
          <el-select v-model="form.fast_model" placeholder="留空则自动选择" filterable clearable allow-create @change="clearAlerts">
            <el-option
              v-for="m in availableModels"
              :key="m.value"
              :label="m.label"
              :value="m.value"
            />
          </el-select>
          <div class="form-tip">
            <el-text size="small" type="info">
              非推理型快速模型，用于调试对话等场景（留空则按提供商自动选择，如 GLM→glm-4-flash）
            </el-text>
          </div>
        </el-form-item>

        <el-form-item label="嵌入模型">
          <el-select v-model="form.embedding_model" placeholder="选择嵌入模型" filterable allow-create @change="clearAlerts">
            <el-option
              v-for="m in availableEmbeddingModels"
              :key="m.value"
              :label="m.label"
              :value="m.value"
            />
          </el-select>
          <div class="form-tip">
            <el-text size="small" type="info">
              用于将文本转换为向量，支持技能语义搜索
            </el-text>
          </div>
        </el-form-item>

        <el-divider content-position="left">降级模型链（可选）</el-divider>

        <el-form-item label="降级模型">
          <div class="fallback-wrap">
            <div class="form-tip" style="margin-bottom: 8px">
              <el-text size="small" type="info">
                主模型调用失败（限流/鉴权/超时）时，按顺序尝试以下模型；留空则不降级。
              </el-text>
            </div>
            <div v-for="(fb, idx) in fallbackModels" :key="idx" class="fallback-row">
              <el-select v-model="fb.provider" placeholder="提供商" style="width: 130px" @change="onFbProviderChange(idx)">
                <el-option
                  v-for="p in providers"
                  :key="p.provider_name"
                  :label="p.display_name"
                  :value="p.provider_name"
                />
              </el-select>
              <el-input v-model="fb.api_key" type="password" show-password style="width: 160px" :placeholder="fb.api_key_set ? '已设置（输入可更新）' : 'API Key'" @input="clearAlerts" />
              <el-input v-model="fb.api_base" style="width: 200px" :placeholder="getProviderApiBase(fb.provider) || 'API 地址'" @input="clearAlerts" />
              <el-select v-model="fb.model" placeholder="深度模型" filterable allow-create style="width: 160px" @change="clearAlerts">
                <el-option v-for="m in (getProviderModels(fb.provider))" :key="m.value" :label="m.label" :value="m.value" />
              </el-select>
              <el-select v-model="fb.fast_model" placeholder="快速模型" filterable allow-create clearable style="width: 160px" @change="clearAlerts">
                <el-option v-for="m in (getProviderModels(fb.provider))" :key="m.value" :label="m.label" :value="m.value" />
              </el-select>
              <el-button type="danger" text :icon="Delete" @click="removeFallback(idx)" />
            </div>
            <el-button size="small" type="primary" plain @click="addFallback">
              <el-icon><Plus /></el-icon> 添加降级模型
            </el-button>
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
          <li>选择要使用的模型</li>
          <li>点击"测试连接"验证配置</li>
          <li>点击"保存配置"保存设置</li>
        </ol>

        <h4>已注册的 Provider</h4>
        <el-table :data="providerTableData" size="small">
          <el-table-column prop="display_name" label="名称" />
          <el-table-column prop="provider_name" label="标识" />
          <el-table-column prop="api_base" label="API 地址" show-overflow-tooltip />
          <el-table-column label="模型" show-overflow-tooltip>
            <template #default="{ row }">
              {{ (row.models || []).map((m: any) => m.value).join(', ') }}
            </template>
          </el-table-column>
          <el-table-column prop="fast_model" label="快速模型" />
        </el-table>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import api from '@/api/index'
import { ElMessage } from 'element-plus'
import { Plus, Delete } from '@element-plus/icons-vue'

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)

const providers = ref<any[]>([])

function getProviderModels(providerName: string): { label: string; value: string }[] {
  const p = providers.value.find(p => p.provider_name === providerName)
  return p?.models || []
}

function getProviderApiBase(providerName: string): string {
  const p = providers.value.find(p => p.provider_name === providerName)
  return p?.api_base || ''
}

function getProviderFastModel(providerName: string): string {
  const p = providers.value.find(p => p.provider_name === providerName)
  return p?.fast_model || ''
}

const availableModels = computed(() => getProviderModels(form.value.provider))

const availableEmbeddingModels = computed(() => [
  { label: 'Ada-002', value: 'text-embedding-ada-002' },
  { label: 'Embedding-3 Small', value: 'text-embedding-3-small' },
  { label: 'Embedding-3 Large', value: 'text-embedding-3-large' },
])

const apiBasePlaceholder = computed(() => getProviderApiBase(form.value.provider) || '请填写 API 地址')

function onProviderChange() {
  clearAlerts()
  const models = getProviderModels(form.value.provider)
  if (models.length > 0 && !models.find(m => m.value === form.value.model)) {
    form.value.model = models[0].value
  }
  form.value.api_base = getProviderApiBase(form.value.provider) || ''
  const fastModel = getProviderFastModel(form.value.provider)
  if (fastModel) {
    form.value.fast_model = fastModel
  }
}

function onFbProviderChange(idx: number) {
  clearAlerts()
  const fb = fallbackModels.value[idx]
  fb.api_base = getProviderApiBase(fb.provider) || ''
  const models = getProviderModels(fb.provider)
  if (models.length > 0) {
    fb.model = models[0].value
  }
  fb.fast_model = getProviderFastModel(fb.provider) || ''
}

const config = ref({
  provider: 'glm',
  api_key_set: false,
  api_base: '',
  model: 'glm-5.2',
  embedding_model: 'text-embedding-ada-002',
  is_configured: false
})

const form = ref({
  provider: 'glm',
  api_key: '',
  api_base: '',
  model: 'glm-5.2',
  fast_model: '',
  embedding_model: 'text-embedding-ada-002'
})

const testResult = ref<any>(null)
const saveResult = ref<any>(null)

function clearAlerts() {
  testResult.value = null
  saveResult.value = null
}

// 降级模型链
interface FallbackModel {
  provider: string
  model: string
  fast_model: string
  api_key: string
  api_base: string
  api_key_set: boolean
}
const fallbackModels = ref<FallbackModel[]>([])

function addFallback() {
  clearAlerts()
  const firstProvider = providers.value[0]?.provider_name || 'qwen'
  fallbackModels.value.push({
    provider: firstProvider,
    model: getProviderModels(firstProvider)[0]?.value || '',
    fast_model: getProviderFastModel(firstProvider) || '',
    api_key: '',
    api_base: getProviderApiBase(firstProvider),
    api_key_set: false,
  })
}
function removeFallback(idx: number) {
  clearAlerts()
  fallbackModels.value.splice(idx, 1)
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
      model: res.model,
      fast_model: res.fast_model || '',
      embedding_model: res.embedding_model
    }
    fallbackModels.value = (res.fallback_models || []).map((f: any) => ({
      provider: f.provider || '',
      model: f.model || '',
      fast_model: f.fast_model || '',
      api_key: '',
      api_base: f.api_base || '',
      api_key_set: !!f.api_key_set,
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
    const payload = {
      ...form.value,
      fallback_models: fallbackModels.value
        .filter(f => f.model && f.model.trim())
        .map(f => ({
          provider: f.provider,
          model: f.model,
          fast_model: f.fast_model || '',
          api_key: f.api_key,
          api_base: f.api_base,
        })),
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
      model: form.value.model,
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

.fallback-wrap {
  width: 100%;
}

.fallback-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
  flex-wrap: wrap;
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
