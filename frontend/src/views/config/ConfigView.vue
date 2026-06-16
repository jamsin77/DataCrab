<template>
  <div class="config-container">
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
          <el-select v-model="form.provider" placeholder="选择提供商">
            <el-option label="OpenAI" value="openai" />
            <el-option label="Azure OpenAI" value="azure" />
            <el-option label="通义千问 (阿里云)" value="qwen" />
            <el-option label="智谱AI (GLM)" value="glm" />
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
            placeholder="可选，默认使用官方地址"
          />
          <div class="form-tip">
            <el-text size="small" type="info">
              可填写自定义API地址，如 http://localhost:8000/v1
            </el-text>
          </div>
        </el-form-item>

        <el-form-item label="对话模型">
          <el-select v-model="form.model" placeholder="选择模型" filterable allow-create>
            <el-option-group label="OpenAI">
              <el-option label="GPT-4" value="gpt-4" />
              <el-option label="GPT-4 Turbo" value="gpt-4-turbo" />
              <el-option label="GPT-4o" value="gpt-4o" />
              <el-option label="GPT-3.5 Turbo" value="gpt-3.5-turbo" />
            </el-option-group>
            <el-option-group label="通义千问">
              <el-option label="通义千问 Max" value="qwen-max" />
              <el-option label="通义千问 Plus" value="qwen-plus" />
              <el-option label="通义千问 Turbo" value="qwen-turbo" />
              <el-option label="通义千问 Long" value="qwen-long" />
            </el-option-group>
            <el-option-group label="智谱AI">
              <el-option label="GLM-5" value="glm-5" />
              <el-option label="GLM-4" value="glm-4" />
              <el-option label="GLM-4 Plus" value="glm-4-plus" />
              <el-option label="GLM-3 Turbo" value="glm-3-turbo" />
            </el-option-group>
            <el-option-group label="Claude">
              <el-option label="Claude 3 Opus" value="claude-3-opus" />
              <el-option label="Claude 3 Sonnet" value="claude-3-sonnet" />
              <el-option label="Claude 3 Haiku" value="claude-3-haiku" />
            </el-option-group>
          </el-select>
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

      <!-- 测试结果 -->
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

      <!-- 保存结果 -->
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

    <!-- 使用说明 -->
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
import { ref, onMounted } from 'vue'
import api from '@/api/index'
import { ElMessage } from 'element-plus'

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)

const config = ref({
  provider: 'openai',
  api_key_set: false,
  api_base: '',
  model: 'gpt-4',
  embedding_model: 'text-embedding-ada-002',
  is_configured: false
})

const form = ref({
  provider: 'openai',
  api_key: '',
  api_base: '',
  model: 'gpt-4',
  embedding_model: 'text-embedding-ada-002'
})

const testResult = ref<any>(null)
const saveResult = ref<any>(null)

const modelProviders = ref([
  { name: 'OpenAI', models: 'gpt-4, gpt-4o, gpt-3.5-turbo', note: '官方API: api.openai.com' },
  { name: 'Azure OpenAI', models: 'gpt-4, gpt-35-turbo', note: '需设置API地址' },
  { name: '通义千问', models: 'qwen-max, qwen-plus, qwen-turbo', note: 'API: dashscope.aliyuncs.com' },
  { name: '智谱AI', models: 'glm-5, glm-4, glm-3-turbo', note: 'API: open.bigmodel.cn' },
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
      embedding_model: res.embedding_model
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
    const res = await api.post('/config/llm', form.value)
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
.config-container {
  padding: 20px;
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