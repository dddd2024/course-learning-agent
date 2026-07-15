<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import { login, register } from '../api/auth'
import { parseApiError } from '../utils/error'
import { readPendingQueue, flushPendingErrorReports } from '../utils/errorReport'
import InkAmbient from '../components/common/InkAmbient.vue'
import { Reading, Connection, DataAnalysis } from '@element-plus/icons-vue'

type TabName = 'login' | 'register'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

// Closure fix Task C1: support ?redirect=/logs so a 401 on /logs can
// return the user to the log center after re-authenticating. The redirect
// target must be a same-site path (starts with '/' but not '//') to
// prevent open-redirect attacks.
function resolveRedirect(): string {
  const raw = route.query.redirect
  if (typeof raw === 'string' && raw.startsWith('/') && !raw.startsWith('//')) {
    return raw
  }
  return '/dashboard'
}

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
  confirmPassword: '',
  email: '',
})

const registerRules: FormRules<typeof registerForm> = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (value !== registerForm.password) callback(new Error('两次输入的密码不一致'))
        else callback()
      },
      trigger: ['blur', 'change'],
    },
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
    // Closure fix Task C1: honor ?redirect so 401 on /logs returns here.
    router.push(resolveRedirect())
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
    // Closure fix Task C1: honor ?redirect on register-then-login too.
    router.push(resolveRedirect())
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
    <InkAmbient />
    <section class="login-story" aria-label="课程学习助手介绍">
      <div class="brand-lockup">
        <el-icon><Reading /></el-icon>
        <span>课程学习助手</span>
      </div>
      <div class="story-copy">
        <p class="story-kicker">AI 驱动的个人学习空间</p>
        <h1>让知识在山水之间，<br>形成清晰的脉络。</h1>
        <p>汇聚课程、资料、计划与证据引用，让每一步学习都有方向，也有迹可循。</p>
        <div class="story-features">
          <span><el-icon><Connection /></el-icon> 知识关联</span>
          <span><el-icon><DataAnalysis /></el-icon> 学习洞察</span>
        </div>
      </div>
    </section>

    <section class="login-panel" aria-labelledby="login-panel-title">
      <div class="panel-heading">
        <p>进入学习空间</p>
        <h2 id="login-panel-title">欢迎回来</h2>
        <span>继续你的课程与学习计划</span>
      </div>

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
            <el-form-item label="确认密码" prop="confirmPassword">
              <el-input
                v-model="registerForm.confirmPassword"
                type="password"
                placeholder="再次输入密码"
                show-password
                @keyup.enter="handleRegister"
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
      <p class="privacy-note">你的课程资料与学习记录仅用于当前账户的个性化学习。</p>
    </section>
  </div>
</template>

<style scoped>
.login-container {
  position: relative;
  min-height: 100dvh;
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(380px, 0.75fr);
  align-items: center;
  overflow: hidden;
  color: var(--ink);
  background-color: var(--paper);
  background-image: url('../assets/ink-login-landscape.webp');
  background-size: cover;
  background-position: center;
}

.login-container::after {
  content: '';
  position: absolute;
  inset: 0 0 0 auto;
  width: 44%;
  background: rgba(247, 243, 233, 0.8);
  border-left: 1px solid rgba(43, 61, 64, 0.15);
  backdrop-filter: blur(20px);
  pointer-events: none;
}

.login-story,
.login-panel {
  position: relative;
  z-index: 1;
}

.login-story {
  align-self: stretch;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 40px 6vw 58px;
}

.brand-lockup {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: var(--ink-night);
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.brand-lockup .el-icon { font-size: 28px; color: var(--indigo-ink); }
.story-copy { max-width: 620px; padding-bottom: 7vh; }
.story-kicker { margin-bottom: 14px; color: var(--indigo-ink); font-size: 12px; font-weight: 600; letter-spacing: 0.18em; }
.story-copy h1 { margin: 0 0 20px; font-size: clamp(42px, 5vw, 74px); font-weight: 500; line-height: 1.25; color: var(--ink); }
.story-copy > p:not(.story-kicker) { max-width: 520px; color: var(--ink-muted); font-size: 16px; line-height: 1.85; letter-spacing: 0.04em; }
.story-features { display: flex; gap: 26px; margin-top: 28px; color: var(--ink-soft); }
.story-features span { display: inline-flex; align-items: center; gap: 8px; }
.story-features .el-icon { color: var(--celadon-strong); }

.login-panel {
  width: min(420px, calc(100vw - 40px));
  justify-self: center;
  padding: 36px 42px 28px;
  background: rgba(250, 247, 239, 0.66);
  border: 1px solid rgba(43, 61, 64, 0.14);
  box-shadow: 0 28px 80px rgba(9, 27, 35, 0.13);
  backdrop-filter: blur(18px);
}

.panel-heading p { color: var(--indigo-ink); font-size: 12px; font-weight: 600; letter-spacing: 0.16em; }
.panel-heading h2 { margin: 7px 0 5px; font-size: 32px; font-weight: 600; }
.panel-heading span { color: var(--ink-muted); font-size: 13px; }
.login-tabs { margin-top: 24px; }
.login-tabs :deep(.el-tabs__nav-wrap::after) { background: var(--border-light); }
.login-tabs :deep(.el-tabs__item) { letter-spacing: 0.08em; }
.submit-btn { width: 100%; margin-top: 8px; min-height: 44px; }
.remember-row { margin-bottom: 8px; }
.privacy-note { margin-top: 18px; color: var(--text-placeholder); font-size: 11px; line-height: 1.6; text-align: center; }

.login-panel :deep(.el-input__wrapper) {
  min-height: 44px;
  background: rgba(255, 253, 247, 0.68);
}

.remember-row :deep(.el-form-item__content) {
  justify-content: flex-start;
}

@media (max-width: 900px) {
  .login-container { grid-template-columns: minmax(0, 1fr); padding: 24px; }
  .login-container::after { inset: auto 0 0; width: 100%; height: 68%; }
  .login-story { align-self: auto; min-height: 260px; padding: 16px 8px 24px; }
  .story-copy { padding: 42px 0 0; }
  .story-copy h1 { font-size: 38px; }
  .story-copy > p:not(.story-kicker), .story-features { display: none; }
  .login-panel { padding: 28px 24px 22px; margin-bottom: 24px; }
}

@media (max-width: 520px) {
  .login-container { padding: 14px; }
  .login-story { min-height: 210px; }
  .brand-lockup { font-size: 16px; }
  .story-copy { padding-top: 28px; }
  .story-copy h1 { font-size: 31px; }
}
</style>
