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
            <el-option label="阿里百炼" value="qwen" />
            <el-option label="智谱AI (GLM)" value="glm" />
            <el-option label="硅基流动" value="siliconflow" />
            <el-option label="自定义服务" value="custom" />
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
          />
          <div class="form-tip">
            <el-text size="small" type="info">
              {{ form.provider === 'custom' ? '可填写自定义API地址，如 http://localhost:8000/v1' : '已自动填入官方地址，如需代理可修改' }}
            </el-text>
          </div>
        </el-form-item>

        <el-form-item label="深度模型">
          <el-select v-model="form.model" placeholder="选择模型" filterable :allow-create="form.provider === 'custom'">
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
          <el-select v-model="form.fast_model" placeholder="留空则自动选择" filterable clearable :allow-create="form.provider === 'custom'">
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
          <el-select v-model="form.embedding_model" placeholder="选择嵌入模型" filterable allow-create>
            <el-option label="Ada-002" value="text-embedding-ada-002" />
            <el-option label="Embedding-3 Small" value="text-embedding-3-small" />
            <el-option label="Embedding-3 Large" value="text-embedding-3-large" />
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
                <el-option label="阿里百炼" value="qwen" />
                <el-option label="智谱AI (GLM)" value="glm" />
                <el-option label="硅基流动" value="siliconflow" />
                <el-option label="自定义" value="custom" />
              </el-select>
              <el-select v-model="fb.model" placeholder="模型" filterable :allow-create="fb.provider === 'custom'" style="width: 190px">
                <el-option v-for="m in (providerModels[fb.provider] || [])" :key="m.value" :label="m.label" :value="m.value" />
              </el-select>
              <el-input v-model="fb.api_key" type="password" show-password style="width: 180px" :placeholder="fb.api_key_set ? '已设置（输入可更新）' : 'API Key'" />
              <el-input v-model="fb.api_base" style="width: 220px" :placeholder="providerBaseUrls[fb.provider] || 'API 地址'" />
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

        <h4>支持的模型服务</h4>
        <el-table :data="modelProviders" size="small">
          <el-table-column prop="name" label="服务商" />
          <el-table-column prop="models" label="推荐模型" />
          <el-table-column prop="note" label="说明" />
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

const providerModels: Record<string, { label: string; value: string }[]> = {
  qwen: [
    { label: 'Qwen3.7-Max', value: 'qwen3.7-max' },
    { label: 'Qwen3.7-Plus', value: 'qwen3.7-plus' },
    { label: 'Qwen3.6-Flash', value: 'qwen3.6-flash' },
    { label: 'DeepSeek-V4-Pro', value: 'deepseek-v4-pro' },
    { label: 'DeepSeek-V4-Flash', value: 'deepseek-v4-flash' },
  ],
  glm: [
    { label: 'GLM-5.2', value: 'glm-5.2' },
    { label: 'GLM-5.1', value: 'glm-5.1' },
    { label: 'GLM-5', value: 'glm-5' },
    { label: 'GLM-4 Plus', value: 'glm-4-plus' },
    { label: 'GLM-4', value: 'glm-4' },
    { label: 'GLM-4 Air', value: 'glm-4-air' },
    { label: 'GLM-4 Flash', value: 'glm-4-flash' },
    { label: 'GLM-4 FlashX', value: 'glm-4-flashx' },
    { label: 'GLM-3 Turbo', value: 'glm-3-turbo' },
  ],
  siliconflow: [
    { label: 'DeepSeek-V3', value: 'deepseek-ai/DeepSeek-V3' },
    { label: 'Qwen2.5-72B', value: 'Qwen/Qwen2.5-72B-Instruct' },
    { label: 'Qwen2.5-Coder-32B', value: 'Qwen/Qwen2.5-Coder-32B-Instruct' },
    { label: 'DeepSeek-V2.5', value: 'deepseek-ai/DeepSeek-V2.5' },
  ],
  custom: [],
}

const providerBaseUrls: Record<string, string> = {
  qwen: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  glm: 'https://open.bigmodel.cn/api/paas/v4',
  siliconflow: 'https://api.siliconflow.cn/v1',
  custom: '',
}

const availableModels = computed(() => providerModels[form.value.provider] || [])

const apiBasePlaceholder = computed(() => {
  const url = providerBaseUrls[form.value.provider]
  return url || '请填写自定义API地址，如 http://localhost:8000/v1'
})

function onProviderChange() {
  const models = providerModels[form.value.provider] || []
  if (models.length > 0 && !models.find(m => m.value === form.value.model)) {
    form.value.model = models[0].value
  }
  form.value.api_base = providerBaseUrls[form.value.provider] || ''
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

// 降级模型链
interface FallbackModel {
  provider: string
  model: string
  api_key: string
  api_base: string
  api_key_set: boolean
}
const fallbackModels = ref<FallbackModel[]>([])

function addFallback() {
  const provider = 'qwen'
  fallbackModels.value.push({
    provider,
    model: '',
    api_key: '',
    api_base: providerBaseUrls[provider] || '',
    api_key_set: false,
  })
}
function removeFallback(idx: number) {
  fallbackModels.value.splice(idx, 1)
}
function onFbProviderChange(idx: number) {
  const fb = fallbackModels.value[idx]
  fb.api_base = providerBaseUrls[fb.provider] || ''
}

const modelProviders = ref([
  { name: '阿里百炼', models: 'qwen3.7-max, qwen3.7-plus, qwen3.6-flash, deepseek-v4-pro', note: 'API: dashscope.aliyuncs.com/compatible-mode/v1' },
  { name: '智谱AI', models: 'glm-5.2, glm-5.1, glm-5, glm-4, glm-3-turbo', note: 'API: open.bigmodel.cn/api/paas/v4' },
  { name: '硅基流动', models: 'DeepSeek-V3, Qwen2.5-72B, Qwen2.5-Coder-32B', note: 'API: api.siliconflow.cn/v1' },
  { name: '本地部署', models: '自定义', note: '如vLLM、Ollama' },
])

onMounted(async () => {
  await loadConfig()
})

async function loadConfig(preserveApiKey = false) {
  loading.value = true
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
      provider: f.provider || 'qwen',
      model: f.model || '',
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
    const res = await api.get('/config/llm/test')
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
