<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import {
  ElMessage,
  ElMessageBox,
  type FormInstance,
  type FormRules,
} from 'element-plus'
import { useAuthStore } from '../stores/auth'
import {
  listConfigs,
  createConfig,
  getActiveConfig,
  updateConfig,
  deleteConfig,
  enableConfig,
  testConfig,
  type LLMConfig,
  type LLMConfigCreate,
  type LLMConfigUpdate,
} from '../api/llmConfig'
import { getSecurityStatus, type SecurityStatus } from '../api/auth'
import { parseApiError } from '../utils/error'

const auth = useAuthStore()

const configs = ref<LLMConfig[]>([])
const listLoading = ref(false)

const activeConfig = ref<LLMConfig | null>(null)
const activeLoading = ref(false)

const securityStatus = ref<SecurityStatus | null>(null)
const securityLoading = ref(false)

const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const editingId = ref<number | undefined>(undefined)
const dialogLoading = ref(false)
const formRef = ref<FormInstance | undefined>(undefined)

interface ProviderOption {
  value: string
  label: string
  baseUrl: string
}

const providerOptions: ProviderOption[] = [
  {
    value: 'OpenAI',
    label: 'OpenAI',
    baseUrl: 'https://api.openai.com/v1',
  },
  {
    value: 'DeepSeek',
    label: 'DeepSeek',
    baseUrl: 'https://api.deepseek.com/v1',
  },
  {
    value: '通义千问',
    label: '通义千问',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  },
  {
    value: '智谱',
    label: '智谱',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
  },
  {
    value: '自定义',
    label: '自定义',
    baseUrl: '',
  },
]

interface ConfigForm {
  provider: string
  name: string
  base_url: string
  model: string
  api_key: string
  temperature: number
  max_tokens: number
  timeout_seconds: number
}

function defaultForm(): ConfigForm {
  return {
    provider: 'OpenAI',
    name: '',
    base_url: 'https://api.openai.com/v1',
    model: '',
    api_key: '',
    temperature: 0.2,
    max_tokens: 2000,
    timeout_seconds: 60,
  }
}

const form = reactive<ConfigForm>(defaultForm())

const rules = computed<FormRules>(() => ({
  provider: [{ required: true, message: '请选择供应商', trigger: 'change' }],
  name: [{ required: true, message: '请输入配置名称', trigger: 'blur' }],
  base_url: [{ required: true, message: '请输入 Base URL', trigger: 'blur' }],
  model: [{ required: true, message: '请输入模型名称', trigger: 'blur' }],
  api_key:
    dialogMode.value === 'create'
      ? [{ required: true, message: '请输入 API Key', trigger: 'blur' }]
      : [],
}))

const testingIds = ref<Set<number>>(new Set())

function testStatusTagType(
  status: string,
): 'success' | 'danger' | 'info' {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'danger'
  return 'info'
}

function testStatusLabel(status: string): string {
  if (status === 'success') return '成功'
  if (status === 'failed') return '失败'
  return '未测试'
}

const activeSummary = computed(() => {
  if (!activeConfig.value) return null
  return `${activeConfig.value.name}（${activeConfig.value.provider} / ${activeConfig.value.model}）`
})

async function fetchConfigs() {
  listLoading.value = true
  try {
    const { data } = await listConfigs()
    configs.value = data.items
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取配置列表失败'))
  } finally {
    listLoading.value = false
  }
}

async function fetchActiveConfig() {
  activeLoading.value = true
  try {
    const { data } = await getActiveConfig()
    activeConfig.value = data.config
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取当前启用配置失败'))
  } finally {
    activeLoading.value = false
  }
}

async function fetchSecurityStatus() {
  securityLoading.value = true
  try {
    const { data } = await getSecurityStatus()
    securityStatus.value = data
  } catch {
    // Non-fatal: the card simply stays hidden if the endpoint is unavailable.
  } finally {
    securityLoading.value = false
  }
}

function securityLabel(value: string): string {
  if (value === 'bcrypt_hash') return 'bcrypt 哈希'
  if (value === 'fernet_encrypted') return 'Fernet 加密'
  return value
}

function handleProviderChange(value: string) {
  const opt = providerOptions.find((o) => o.value === value)
  if (!opt) return
  form.base_url = opt.baseUrl
}

function openCreateDialog() {
  dialogMode.value = 'create'
  editingId.value = undefined
  Object.assign(form, defaultForm())
  dialogVisible.value = true
  nextTick(() => {
    formRef.value?.clearValidate()
  })
}

function openEditDialog(row: LLMConfig) {
  dialogMode.value = 'edit'
  editingId.value = row.id
  form.provider = row.provider
  form.name = row.name
  form.base_url = row.base_url
  form.model = row.model
  form.api_key = ''
  form.temperature = row.temperature
  form.max_tokens = row.max_tokens
  form.timeout_seconds = row.timeout_seconds
  dialogVisible.value = true
  nextTick(() => {
    formRef.value?.clearValidate()
  })
}

async function handleSubmit() {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  dialogLoading.value = true
  try {
    if (dialogMode.value === 'create') {
      const payload: LLMConfigCreate = {
        provider: form.provider,
        name: form.name,
        base_url: form.base_url,
        model: form.model,
        api_key: form.api_key,
        temperature: form.temperature,
        max_tokens: form.max_tokens,
        timeout_seconds: form.timeout_seconds,
      }
      await createConfig(payload)
      ElMessage.success('配置已创建')
    } else {
      const payload: LLMConfigUpdate = {
        provider: form.provider,
        name: form.name,
        base_url: form.base_url,
        model: form.model,
        temperature: form.temperature,
        max_tokens: form.max_tokens,
        timeout_seconds: form.timeout_seconds,
      }
      if (form.api_key) {
        payload.api_key = form.api_key
      }
      await updateConfig(editingId.value as number, payload)
      ElMessage.success('配置已更新')
    }
    dialogVisible.value = false
    fetchConfigs()
    fetchActiveConfig()
  } catch (err) {
    ElMessage.error(
      parseApiError(
        err,
        dialogMode.value === 'create' ? '创建配置失败' : '更新配置失败',
      ),
    )
  } finally {
    dialogLoading.value = false
  }
}

async function handleEnable(row: LLMConfig) {
  if (row.last_test_status !== 'success') {
    ElMessage.warning('请先测试连接；只有验证成功的配置才能启用')
    return
  }
  try {
    await enableConfig(row.id)
    ElMessage.success(`已启用「${row.name}」`)
    fetchConfigs()
    fetchActiveConfig()
  } catch (err) {
    ElMessage.error(parseApiError(err, '启用配置失败'))
  }
}

async function handleTest(row: LLMConfig) {
  testingIds.value.add(row.id)
  try {
    const { data } = await testConfig(row.id)
    if (data.status === 'success') {
      ElMessage.success('连接成功')
    } else {
      // Show the backend diagnostic error in a dialog so the full message
      // is readable (HTTP status / non-JSON / missing-choices reasons can
      // be longer than a toast).
      await ElMessageBox.alert(
        data.error || '未知错误',
        `「${row.name}」连接失败`,
        { type: 'error', confirmButtonText: '知道了' },
      )
    }
    fetchConfigs()
  } catch (err) {
    ElMessage.error(parseApiError(err, '测试连接失败'))
  } finally {
    testingIds.value.delete(row.id)
  }
}

async function handleDelete(row: LLMConfig) {
  try {
    await ElMessageBox.confirm(
      `确定删除配置「${row.name}」吗？此操作不可恢复。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteConfig(row.id)
    ElMessage.success('配置已删除')
    fetchConfigs()
    fetchActiveConfig()
  } catch (err) {
    ElMessage.error(parseApiError(err, '删除配置失败'))
  }
}

onMounted(() => {
  fetchConfigs()
  fetchActiveConfig()
  fetchSecurityStatus()
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <h2 class="title">个人中心</h2>
    </div>

    <el-card v-loading="activeLoading" class="section-card" shadow="never">
      <template #header>
        <div class="section-title">用户信息</div>
      </template>
      <div class="user-info">
        <div class="info-row">
          <span class="info-label">用户名：</span>
          <span class="info-value">{{ auth.username || '游客' }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">当前启用模型：</span>
          <span v-if="activeSummary" class="info-value">{{ activeSummary }}</span>
          <span v-else class="info-value info-empty">未配置</span>
          <el-tag
            v-if="!activeConfig && !activeLoading"
            type="warning"
            size="small"
            effect="plain"
            class="inline-tag"
          >
            建议尽快配置
          </el-tag>
        </div>
        <div class="info-row">
          <span class="info-label">当前模式：</span>
          <el-tag v-if="activeConfig" type="success" size="small">
            用户配置模式（Real）
          </el-tag>
          <el-tag v-else type="info" size="small">Mock / 系统模式</el-tag>
          <el-tooltip placement="right" effect="light">
            <template #content>
              <div class="mode-tip">
                <p>
                  <b>Mock 模式：</b>使用预设的模拟回复，无需 API Key，适合体验功能流程。
                </p>
                <p>
                  <b>Real 模式：</b>连接真实 LLM API（如 OpenAI、DeepSeek），获得智能问答和内容生成。
                </p>
              </div>
            </template>
            <el-icon class="tip-icon"><QuestionFilled /></el-icon>
          </el-tooltip>
        </div>
      </div>
    </el-card>

    <el-card
      v-if="securityStatus"
      v-loading="securityLoading"
      class="section-card"
      shadow="never"
    >
      <template #header>
        <div class="section-title">安全状态</div>
      </template>
      <div class="user-info">
        <div class="info-row">
          <span class="info-label">密码存储：</span>
          <el-tag type="success" size="small">
            {{ securityLabel(securityStatus.password_storage) }}
          </el-tag>
        </div>
        <div class="info-row">
          <span class="info-label">API Key 存储：</span>
          <el-tag type="success" size="small">
            {{ securityLabel(securityStatus.api_key_storage) }}
          </el-tag>
        </div>
        <div class="info-row">
          <span class="info-label">Token 有效期：</span>
          <span class="info-value">
            {{ securityStatus.token_expiry_minutes }} 分钟
          </span>
        </div>
        <div class="info-row">
          <span class="info-label">运行环境：</span>
          <el-tag
            :type="securityStatus.environment === 'production' ? 'warning' : 'info'"
            size="small"
          >
            {{ securityStatus.environment }}
          </el-tag>
        </div>
        <!-- Task C: the "default secret" warning is developer-facing and
             removed from the normal user UI. The backend still refuses to
             start with a default secret in production. -->
      </div>
    </el-card>

    <el-card class="section-card" shadow="never">
      <template #header>
        <div class="section-header">
          <div class="section-title">LLM 配置列表</div>
          <el-button type="primary" @click="openCreateDialog">新增配置</el-button>
        </div>
      </template>
      <el-alert
        v-if="!activeConfig && !activeLoading"
        type="warning"
        :closable="false"
        show-icon
        class="config-alert"
      >
        <template #title>
          <div class="alert-row">
            <span class="alert-text">
              当前使用 Mock 模式（预设回复），配置 LLM API 后可获得真实的智能问答、知识提取和测验生成功能。
            </span>
            <el-button type="primary" size="small" @click="openCreateDialog">
              立即配置
            </el-button>
          </div>
        </template>
      </el-alert>
      <el-table
        v-loading="listLoading"
        :data="configs"
        stripe
        empty-text="暂无配置"
      >
        <el-table-column
          prop="name"
          label="名称"
          min-width="140"
          show-overflow-tooltip
        />
        <el-table-column
          prop="provider"
          label="供应商"
          width="120"
          align="center"
        />
        <el-table-column
          prop="base_url"
          label="Base URL"
          min-width="220"
          show-overflow-tooltip
        />
        <el-table-column
          prop="model"
          label="模型"
          min-width="160"
          show-overflow-tooltip
        />
        <el-table-column
          prop="api_key_masked"
          label="API Key"
          width="150"
          align="center"
        />
        <el-table-column label="启用" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
              {{ row.enabled ? '已启用' : '未启用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="默认" width="80" align="center">
          <template #default="{ row }">
            <el-tag :type="row.is_default ? 'warning' : 'info'" size="small">
              {{ row.is_default ? '默认' : '-' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="测试状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag
              :type="testStatusTagType(row.last_test_status)"
              size="small"
            >
              {{ testStatusLabel(row.last_test_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column
          label="操作"
          width="260"
          align="center"
          fixed="right"
        >
          <template #default="{ row }">
            <el-button
              size="small"
              :type="row.last_test_status === 'success' ? 'success' : 'info'"
              :disabled="row.enabled"
              @click="handleEnable(row)"
            >
              {{ row.last_test_status === 'success' ? '启用' : '先测试' }}
            </el-button>
            <el-button
              size="small"
              type="primary"
              :loading="testingIds.has(row.id)"
              @click="handleTest(row)"
            >
              测试
            </el-button>
            <el-button size="small" @click="openEditDialog(row)">编辑</el-button>
            <el-button
              size="small"
              type="danger"
              @click="handleDelete(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      :title="dialogMode === 'create' ? '新增配置' : '编辑配置'"
      width="560px"
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
      >
        <el-form-item label="供应商" prop="provider">
          <el-select
            v-model="form.provider"
            style="width: 100%"
            @change="handleProviderChange"
          >
            <el-option
              v-for="opt in providerOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
          <div class="form-help">
            选择 LLM 服务商，会自动填充对应的 Base URL；选择「自定义」可手动填写。
          </div>
        </el-form-item>
        <el-form-item label="配置名称" prop="name">
          <el-input
            v-model="form.name"
            placeholder="例如：SenseNova DeepSeek V4 Flash"
          />
          <div class="form-help">
            仅用于在本列表中区分多个配置，不是发送给模型的模型 ID。
          </div>
        </el-form-item>
        <el-form-item label="Base URL" prop="base_url">
          <el-input
            v-model="form.base_url"
            placeholder="例如：https://token.sensenova.cn/v1"
          />
          <div class="form-help">
            兼容 OpenAI 协议的接口地址。不要填写 /chat/completions，系统会自动拼接。
          </div>
        </el-form-item>
        <el-form-item label="模型" prop="model">
          <el-input
            v-model="form.model"
            placeholder="例如：deepseek-v4-flash"
          />
          <div class="form-help">
            填写供应商控制台显示的精确 Model ID，错误或拼写的模型名会导致调用失败。
          </div>
        </el-form-item>
        <el-form-item label="API Key" prop="api_key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            :placeholder="
              dialogMode === 'edit' ? '留空则不修改' : '请输入 API Key'
            "
          />
          <div class="form-help">
            仅保存加密后的密文；编辑时留空表示沿用原密钥。可在供应商控制台的 API Keys 页面创建。
          </div>
        </el-form-item>
        <el-form-item label="Temperature">
          <el-input-number
            v-model="form.temperature"
            :min="0"
            :max="2"
            :step="0.1"
            style="width: 100%"
          />
          <div class="form-help">
            采样温度，0 更确定稳定，越高越随机有创造性。问答建议 0.2，写作可适当调高。
          </div>
        </el-form-item>
        <el-form-item label="Max Tokens">
          <el-input-number
            v-model="form.max_tokens"
            :min="1"
            :step="100"
            style="width: 100%"
          />
          <div class="form-help">
            单次回复的最大 Token 数，超长内容生成（如测验、摘要）建议设置到 2000 以上。
          </div>
        </el-form-item>
        <el-form-item label="Timeout (秒)">
          <el-input-number
            v-model="form.timeout_seconds"
            :min="1"
            :step="10"
            style="width: 100%"
          />
          <div class="form-help">
            单次请求超时时间，模型响应较慢或内容较长时适当调大。
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="dialogLoading"
          @click="handleSubmit"
        >
          {{ dialogMode === 'create' ? '创建' : '保存' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  background: #fff;
  padding: 24px;
  border-radius: 4px;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.title {
  font-size: 20px;
  margin: 0;
  color: #303133;
}

.section-card {
  margin-bottom: 20px;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.user-info {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.info-row {
  display: flex;
  align-items: center;
  font-size: 14px;
}

.info-label {
  width: 130px;
  color: #606266;
  font-weight: 600;
}

.info-value {
  color: #303133;
}

.info-empty {
  color: #909399;
}

.form-help {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.5;
  color: #909399;
}

.inline-tag {
  margin-left: 8px;
}

.tip-icon {
  margin-left: 6px;
  font-size: 14px;
  color: #909399;
  cursor: help;
  vertical-align: middle;
}

.mode-tip {
  max-width: 320px;
  font-size: 12px;
  line-height: 1.6;
}

.mode-tip p {
  margin: 0 0 6px;
}

.mode-tip p:last-child {
  margin-bottom: 0;
}

.config-alert {
  margin-bottom: 16px;
}

.alert-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  width: 100%;
}

.alert-text {
  flex: 1;
  line-height: 1.5;
}
</style>
