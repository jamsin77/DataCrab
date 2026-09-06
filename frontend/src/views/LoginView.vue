<template>
  <div class="login-container">
    <div class="login-card">
      <h1 class="title">DataCrab</h1>
      <p class="subtitle">{{ t('login.subtitle') }}</p>
      <el-form ref="formRef" :model="form" :rules="rules" @submit.prevent="handleLogin">
        <el-form-item prop="username">
          <el-input
            v-model="form.username"
            :placeholder="t('login.username')"
            prefix-icon="User"
            size="large"
          />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            :placeholder="t('login.password')"
            prefix-icon="Lock"
            size="large"
            show-password
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            size="large"
            :loading="loading"
            style="width: 100%"
            @click="handleLogin"
          >
            {{ t('login.signIn') }}
          </el-button>
        </el-form-item>
      </el-form>
      <div class="register-link">
        {{ t('login.noAccount') }}
        <el-link type="primary" @click="showRegister = true">{{ t('login.register') }}</el-link>
        <span class="divider">|</span>
        <el-link type="primary" @click="showReset = true">{{ t('login.resetPassword') }}</el-link>
      </div>
      <div v-if="version" class="login-version">v{{ version }}</div>
    </div>

    <!-- 注册对话框 -->
    <el-dialog v-model="showRegister" :title="t('login.registerTitle')" width="400px">
      <el-form ref="registerFormRef" :model="registerForm" :rules="registerRules">
        <el-form-item prop="username" :label="t('login.username')">
          <el-input v-model="registerForm.username" />
        </el-form-item>
        <el-form-item prop="email" :label="t('login.email')">
          <el-input v-model="registerForm.email" />
        </el-form-item>
        <el-form-item prop="password" :label="t('login.password')">
          <el-input v-model="registerForm.password" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showRegister = false">{{ t('login.cancel') }}</el-button>
        <el-button type="primary" :loading="registerLoading" @click="handleRegister">{{ t('login.register') }}</el-button>
      </template>
    </el-dialog>

    <!-- 修改密码对话框 -->
    <el-dialog v-model="showReset" :title="t('login.resetTitle')" width="400px">
      <el-form ref="resetFormRef" :model="resetForm" :rules="resetRules">
        <el-form-item prop="username" :label="t('login.username')">
          <el-input v-model="resetForm.username" />
        </el-form-item>
        <el-form-item prop="old_password" :label="t('login.oldPassword')">
          <el-input v-model="resetForm.old_password" type="password" show-password />
        </el-form-item>
        <el-form-item prop="new_password" :label="t('login.newPassword')">
          <el-input v-model="resetForm.new_password" type="password" show-password />
        </el-form-item>
        <el-form-item prop="confirm_password" :label="t('login.confirmPassword')">
          <el-input v-model="resetForm.confirm_password" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showReset = false">{{ t('login.cancel') }}</el-button>
        <el-button type="primary" :loading="resetLoading" @click="handleReset">{{ t('login.confirmModify') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { useVersionStore } from '@/stores/version'
import { authApi } from '@/api/auth'
import { ElMessage } from 'element-plus'
import type { FormInstance } from 'element-plus'

const { t } = useI18n()
const router = useRouter()
const authStore = useAuthStore()
const versionStore = useVersionStore()
const version = ref('')

onMounted(async () => {
  version.value = await versionStore.loadVersion()
})

const formRef = ref<FormInstance>()
const registerFormRef = ref<FormInstance>()
const loading = ref(false)
const showRegister = ref(false)
const registerLoading = ref(false)
const showReset = ref(false)
const resetLoading = ref(false)
const resetFormRef = ref<FormInstance>()

const form = reactive({ username: '', password: '' })
const rules = {
  username: [{ required: true, message: t('login.rules.usernameRequired'), trigger: 'blur' }],
  password: [
    { required: true, message: t('login.rules.passwordRequired'), trigger: 'blur' },
    { min: 6, message: t('login.rules.passwordMin'), trigger: 'blur' },
  ],
}

const registerForm = reactive({ username: '', email: '', password: '' })
const registerRules = {
  username: [{ required: true, message: t('login.rules.usernameRequired'), trigger: 'blur' }],
  email: [
    { required: true, message: t('login.rules.emailRequired'), trigger: 'blur' },
    { type: 'email' as const, message: t('login.rules.emailInvalid'), trigger: 'blur' },
  ],
  password: [
    { required: true, message: t('login.rules.passwordRequired'), trigger: 'blur' },
    { min: 6, message: t('login.rules.passwordMin'), trigger: 'blur' },
  ],
}

function extractError(e: any): string {
  if (e?.response?.data?.detail) {
    const detail = e.response.data.detail
    if (typeof detail === 'string') return detail
    // Pydantic验证错误格式: [{type, loc, msg}, ...]
    if (Array.isArray(detail)) {
      return detail.map((d: any) => d.msg || String(d)).join('; ')
    }
  }
  return e?.message || t('common.operationFailed')
}

async function handleLogin() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    await authStore.login(form.username, form.password)
    ElMessage.success(t('login.signInSuccess'))
    router.push('/')
  } catch (e: any) {
    ElMessage.error(extractError(e) || t('login.signInFailed'))
  } finally {
    loading.value = false
  }
}

const resetForm = reactive({ username: '', old_password: '', new_password: '', confirm_password: '' })

const resetRules = {
  username: [{ required: true, message: t('login.rules.usernameRequired'), trigger: 'blur' }],
  old_password: [
    { required: true, message: t('login.rules.oldPasswordRequired'), trigger: 'blur' },
    { min: 6, message: t('login.rules.passwordMin'), trigger: 'blur' },
  ],
  new_password: [
    { required: true, message: t('login.rules.newPasswordRequired'), trigger: 'blur' },
    { min: 6, message: t('login.rules.passwordMin'), trigger: 'blur' },
  ],
  confirm_password: [
    { required: true, message: t('login.rules.confirmPasswordRequired'), trigger: 'blur' },
    {
      validator: (_rule: any, value: string, callback: any) => {
        if (value !== resetForm.new_password) {
          callback(new Error(t('login.rules.passwordMismatch')))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
}

async function handleReset() {
  const valid = await resetFormRef.value?.validate().catch(() => false)
  if (!valid) return
  resetLoading.value = true
  try {
    await authApi.resetPassword(resetForm.username, resetForm.old_password, resetForm.new_password)
    ElMessage.success(t('login.resetSuccess'))
    showReset.value = false
    resetForm.username = ''
    resetForm.old_password = ''
    resetForm.new_password = ''
    resetForm.confirm_password = ''
  } catch (e: any) {
    ElMessage.error(extractError(e) || t('login.resetFailed'))
  } finally {
    resetLoading.value = false
  }
}

async function handleRegister() {
  const valid = await registerFormRef.value?.validate().catch(() => false)
  if (!valid) return
  registerLoading.value = true
  try {
    await authStore.register(registerForm.username, registerForm.email, registerForm.password)
    ElMessage.success(t('login.registerSuccess'))
    showRegister.value = false
  } catch (e: any) {
    ElMessage.error(extractError(e) || t('login.registerFailed'))
  } finally {
    registerLoading.value = false
  }
}
</script>

<style lang="scss" scoped>
.login-container {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.login-card {
  width: 400px;
  padding: 40px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);

  .title {
    text-align: center;
    font-size: 32px;
    font-weight: 700;
    margin: 0 0 8px;
    color: #333;
  }

  .subtitle {
    text-align: center;
    color: #999;
    margin: 0 0 32px;
  }

  .register-link {
    text-align: center;
    color: #999;

    .divider {
      margin: 0 8px;
      color: #dcdfe6;
    }
  }

  .login-version {
    text-align: center;
    font-size: 12px;
    color: #c0c4cc;
    margin-top: 16px;
  }
}
</style>
