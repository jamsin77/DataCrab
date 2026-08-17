<template>
  <div class="login-container">
    <div class="login-card">
      <h1 class="title">DataCrab</h1>
      <p class="subtitle">数据工程智能体</p>
      <el-form ref="formRef" :model="form" :rules="rules" @submit.prevent="handleLogin">
        <el-form-item prop="username">
          <el-input
            v-model="form.username"
            placeholder="用户名"
            prefix-icon="User"
            size="large"
          />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
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
            登录
          </el-button>
        </el-form-item>
      </el-form>
      <div class="register-link">
        还没有账号？
        <el-link type="primary" @click="showRegister = true">注册</el-link>
        <span class="divider">|</span>
        <el-link type="primary" @click="showReset = true">修改密码</el-link>
      </div>
      <div v-if="version" class="login-version">v{{ version }}</div>
    </div>

    <!-- 注册对话框 -->
    <el-dialog v-model="showRegister" title="注册" width="400px">
      <el-form ref="registerFormRef" :model="registerForm" :rules="registerRules">
        <el-form-item prop="username" label="用户名">
          <el-input v-model="registerForm.username" />
        </el-form-item>
        <el-form-item prop="email" label="邮箱">
          <el-input v-model="registerForm.email" />
        </el-form-item>
        <el-form-item prop="password" label="密码">
          <el-input v-model="registerForm.password" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showRegister = false">取消</el-button>
        <el-button type="primary" :loading="registerLoading" @click="handleRegister">注册</el-button>
      </template>
    </el-dialog>

    <!-- 修改密码对话框 -->
    <el-dialog v-model="showReset" title="修改密码" width="400px">
      <el-form ref="resetFormRef" :model="resetForm" :rules="resetRules">
        <el-form-item prop="username" label="用户名">
          <el-input v-model="resetForm.username" />
        </el-form-item>
        <el-form-item prop="old_password" label="旧密码">
          <el-input v-model="resetForm.old_password" type="password" show-password />
        </el-form-item>
        <el-form-item prop="new_password" label="新密码">
          <el-input v-model="resetForm.new_password" type="password" show-password />
        </el-form-item>
        <el-form-item prop="confirm_password" label="确认新密码">
          <el-input v-model="resetForm.confirm_password" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showReset = false">取消</el-button>
        <el-button type="primary" :loading="resetLoading" @click="handleReset">确认修改</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useVersionStore } from '@/stores/version'
import { authApi } from '@/api/auth'
import { ElMessage } from 'element-plus'
import type { FormInstance } from 'element-plus'

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
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少6位', trigger: 'blur' },
  ],
}

const registerForm = reactive({ username: '', email: '', password: '' })
const registerRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email' as const, message: '请输入有效邮箱', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少6位', trigger: 'blur' },
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
  return e?.message || '操作失败'
}

async function handleLogin() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    await authStore.login(form.username, form.password)
    ElMessage.success('登录成功')
    router.push('/')
  } catch (e: any) {
    ElMessage.error(extractError(e) || '登录失败')
  } finally {
    loading.value = false
  }
}

const resetForm = reactive({ username: '', old_password: '', new_password: '', confirm_password: '' })

const resetRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  old_password: [
    { required: true, message: '请输入旧密码', trigger: 'blur' },
    { min: 6, message: '密码至少6位', trigger: 'blur' },
  ],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '密码至少6位', trigger: 'blur' },
  ],
  confirm_password: [
    { required: true, message: '请确认新密码', trigger: 'blur' },
    {
      validator: (_rule: any, value: string, callback: any) => {
        if (value !== resetForm.new_password) {
          callback(new Error('两次输入的密码不一致'))
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
    ElMessage.success('密码修改成功，请用新密码登录')
    showReset.value = false
    resetForm.username = ''
    resetForm.old_password = ''
    resetForm.new_password = ''
    resetForm.confirm_password = ''
  } catch (e: any) {
    ElMessage.error(extractError(e) || '修改失败')
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
    ElMessage.success('注册成功，请登录')
    showRegister.value = false
  } catch (e: any) {
    ElMessage.error(extractError(e) || '注册失败')
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
