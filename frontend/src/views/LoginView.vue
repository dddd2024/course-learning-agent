<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import { login, register } from '../api/auth'
import { parseApiError } from '../utils/error'
import { readPendingQueue, flushPendingErrorReports } from '../utils/errorReport'

type TabName = 'login' | 'register'

const router = useRouter()
const auth = useAuthStore()

const activeTab = ref<TabName>('login')
const loading = ref(false)

const loginFormRef = ref<FormInstance>()
const loginForm = reactive({
  username: '',
  password: '',
  remember: false,
})

const loginRules: FormRules<typeof loginForm> = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' },
  ],
}

const registerFormRef = ref<FormInstance>()
const registerForm = reactive({
  username: '',
  password: '',
  email: '',
})

const registerRules: FormRules<typeof registerForm> = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' },
  ],
  email: [{ type: 'email', message: '邮箱格式不正确', trigger: 'blur' }],
}

async function handleLogin() {
  if (!loginFormRef.value) return
  try {
    await loginFormRef.value.validate()
  } catch {
    return
  }
  loading.value = true
  try {
    const { data } = await login({
      username: loginForm.username,
      password: loginForm.password,
    })
    auth.setToken(data.access_token, loginForm.username, loginForm.remember)
    ElMessage.success('登录成功')
    // Logs-endpoint fix Task B3: if there are pending error reports from
    // a previous session (collected while the backend was down or the
    // token had expired), flush them now so they land in the log center
    // instead of lingering in sessionStorage forever.
    if (readPendingQueue().length > 0) {
      flushPendingErrorReports().catch(() => {
        // best-effort; the queue is retained on failure
      })
    }
    router.push('/dashboard')
  } catch (err) {
    ElMessage.error(parseApiError(err, '登录失败，请重试'))
  } finally {
    loading.value = false
  }
}

async function handleRegister() {
  if (!registerFormRef.value) return
  try {
    await registerFormRef.value.validate()
  } catch {
    return
  }
  loading.value = true
  try {
    await register({
      username: registerForm.username,
      password: registerForm.password,
      email: registerForm.email || undefined,
    })
    ElMessage.success('注册成功，即将自动登录')
    // 自动登录
    const { data } = await login({
      username: registerForm.username,
      password: registerForm.password,
    })
    auth.setToken(data.access_token, registerForm.username)
    // Logs-endpoint fix Task B3: same auto-flush as login.
    if (readPendingQueue().length > 0) {
      flushPendingErrorReports().catch(() => {
        // best-effort; the queue is retained on failure
      })
    }
    router.push('/dashboard')
  } catch (err) {
    ElMessage.error(parseApiError(err, '注册失败，请重试'))
  } finally {
    loading.value = false
  }
}

function switchTab(tab: string) {
  activeTab.value = tab as TabName
}
</script>

<template>
  <div class="login-container">
    <el-card class="login-card">
      <h1 class="login-title">课程学习助手</h1>
      <p class="login-desc">Agent 平台</p>

      <el-tabs v-model="activeTab" class="login-tabs" @tab-change="switchTab">
        <el-tab-pane label="登录" name="login">
          <el-form
            ref="loginFormRef"
            :model="loginForm"
            :rules="loginRules"
            label-position="top"
            size="large"
            @submit.prevent
          >
            <el-form-item label="用户名" prop="username">
              <el-input
                v-model="loginForm.username"
                placeholder="请输入用户名"
                clearable
              />
            </el-form-item>
            <el-form-item label="密码" prop="password">
              <el-input
                v-model="loginForm.password"
                type="password"
                placeholder="请输入密码"
                show-password
                @keyup.enter="handleLogin"
              />
            </el-form-item>
            <el-form-item class="remember-row">
              <el-checkbox v-model="loginForm.remember">
                记住登录（否则关闭浏览器后需重新登录）
              </el-checkbox>
            </el-form-item>
            <el-button
              type="primary"
              class="submit-btn"
              :loading="loading"
              @click="handleLogin"
            >
              登录
            </el-button>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="注册" name="register">
          <el-form
            ref="registerFormRef"
            :model="registerForm"
            :rules="registerRules"
            label-position="top"
            size="large"
            @submit.prevent
          >
            <el-form-item label="用户名" prop="username">
              <el-input
                v-model="registerForm.username"
                placeholder="请输入用户名"
                clearable
              />
            </el-form-item>
            <el-form-item label="密码" prop="password">
              <el-input
                v-model="registerForm.password"
                type="password"
                placeholder="至少 6 位"
                show-password
              />
            </el-form-item>
            <el-form-item label="邮箱（选填）" prop="email">
              <el-input
                v-model="registerForm.email"
                placeholder="选填"
                clearable
              />
            </el-form-item>
            <el-button
              type="primary"
              class="submit-btn"
              :loading="loading"
              @click="handleRegister"
            >
              注册并登录
            </el-button>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<style scoped>
.login-container {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.login-card {
  width: 400px;
  padding: 24px 16px 8px;
}

.login-title {
  font-size: 24px;
  color: #303133;
  text-align: center;
  margin-bottom: 4px;
}

.login-desc {
  color: #909399;
  font-size: 14px;
  text-align: center;
  margin-bottom: 16px;
}

.login-tabs {
  margin-top: 8px;
}

.submit-btn {
  width: 100%;
  margin-top: 8px;
}

.remember-row {
  margin-bottom: 8px;
}

.remember-row :deep(.el-form-item__content) {
  justify-content: flex-start;
}
</style>
