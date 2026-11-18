<template>
  <section class="page" data-module="auth">
    <header class="page-head">
      <div>
        <h2>凭证管理管理</h2>
        <p class="page-desc">维护认证凭证，围绕凭证编号、凭证类型、关联数据源、凭证内容做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">登记认证凭证</button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">导出凭证管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无凭证管理数据，可先登记认证凭证</td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记认证凭证</h3>
        <label v-for="field in columns" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条凭证管理记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <section class="panel" data-testid="ledger-panel">
      <header class="panel-head">
        <div>
          <h3>源端接入档案 · 待确认台账</h3>
          <p class="page-desc">
            认证服务把源端接入档案作为只读输入读取，续期或吊销时回写凭据版本与可用性；
            确认后生成可回读记录，重复确认会被拒绝。
          </p>
        </div>
        <div class="panel-meta">
          <span class="badge" data-testid="ledger-pending">
            待确认 {{ ledger.filter((row) => row.确认状态 === '待确认').length }} 条
          </span>
          <button class="btn" data-testid="refresh-ledger" type="button" @click="reloadLedger">
            刷新台账
          </button>
        </div>
      </header>

      <p v-if="ledgerMessage" class="panel-message" data-testid="ledger-message">{{ ledgerMessage }}</p>

      <div class="profile-list" role="table" aria-label="待确认台账">
        <div class="profile-row ledger-row profile-row-9 profile-head" role="row">
          <span>记录编号</span><span>源端编号</span><span>凭证编号</span><span>凭据版本</span>
          <span>可用状态</span><span>档案版本</span><span>确认状态</span><span>回读状态</span><span>可执行动作</span>
        </div>
        <div
          v-for="row in ledger"
          :key="String(row.id)"
          class="profile-row ledger-row profile-row-9"
          role="row"
          :data-testid="`ledger-${row.id}`"
          :data-confirm="String(row.确认状态)"
        >
          <span>{{ row.记录编号 }}</span>
          <span>{{ row.源端编号 }}</span>
          <span>{{ row.凭证编号 }}</span>
          <span>{{ row.凭据版本 }}</span>
          <span>{{ row.可用状态 }}</span>
          <span>{{ row.档案版本 }}</span>
          <span>{{ row.确认状态 }}</span>
          <span>{{ row.回读状态 }}</span>
          <span class="row-actions">
            <button
              v-if="row.确认状态 === '待确认'"
              class="link"
              type="button"
              :data-testid="`confirm-${row.id}`"
              @click="confirmLedger(row)"
            >
              确认并入账
            </button>
            <span v-else class="page-desc">已入账</span>
          </span>
        </div>
        <p v-if="!ledger.length" class="empty-state">暂无待确认的接入档案</p>
      </div>

      <h4 class="panel-subtitle">可回读记录</h4>
      <div class="profile-list" role="table" aria-label="可回读记录" data-testid="readback-table">
        <div class="profile-row readback-row profile-row-6 profile-head" role="row">
          <span>回读编号</span><span>源端编号</span><span>凭据版本</span><span>可用状态</span><span>核对结果</span><span>回读时间</span>
        </div>
        <div
          v-for="row in readbacks"
          :key="String(row.id)"
          class="profile-row readback-row profile-row-6"
          role="row"
          :data-testid="`readback-${row.id}`"
        >
          <span>{{ row.回读编号 }}</span>
          <span>{{ row.源端编号 }}</span>
          <span>{{ row.凭据版本 }}</span>
          <span>{{ row.可用状态 }}</span>
          <span>{{ row.核对结果 }}</span>
          <span>{{ row.回读时间 }}</span>
        </div>
        <p v-if="!readbacks.length" class="empty-state">尚未产生回读记录，确认台账后生成</p>
      </div>

      <h4 class="panel-subtitle">接入档案只读视图 · 返回数据源核对结果</h4>
      <div class="profile-list" role="table" aria-label="接入档案只读视图" data-testid="auth-profile-table">
        <div class="profile-row auth-profile-row profile-row-7 profile-head" role="row">
          <span>源端编号</span><span>凭据版本</span><span>接入地址</span><span>校验结果</span>
          <span>可用状态</span><span>核对结果</span><span>失败原因</span>
        </div>
        <div
          v-for="row in profiles"
          :key="String(row.档案编号)"
          class="profile-row auth-profile-row profile-row-7"
          role="row"
          :data-testid="`auth-profile-${row.源端编号}`"
        >
          <span>{{ row.源端编号 }}</span>
          <span>{{ row.凭据版本 }}</span>
          <span class="cell-wrap">{{ row.接入地址 }}</span>
          <span>{{ row.校验结果 }}</span>
          <span>{{ row.可用状态 }}</span>
          <span>{{ row.是否可执行 ? '一致' : '需处理' }}</span>
          <span class="cell-wrap error-text">{{ row.失败原因 || '—' }}</span>
        </div>
        <p v-if="!profiles.length" class="empty-state">暂无源端接入档案</p>
      </div>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

type LedgerRow = Record<string, string | number | null>
type ProfileRow = Record<string, string | number | boolean | null>

const ENDPOINT = '/api/auth'
const columns = ["凭证编号", "凭证类型", "关联数据源", "凭证内容", "有效期至", "创建时间", "最后使用", "凭证状态"]
const actions = ["续期凭证", "吊销凭证"]
const statuses = ["有效", "即将过期", "已过期", "已吊销"]
const metricNames = ["有效凭证", "即将过期凭证", "已过期凭证"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
const ledger = ref<LedgerRow[]>([])
const readbacks = ref<LedgerRow[]>([])
const profiles = ref<ProfileRow[]>([])
const ledgerMessage = ref('')
const stats = computed(() => [
  { label: metricNames[0], value: total.value },
  { label: metricNames[1], value: rows.value.filter((row) => row.status === statuses[1]).length },
  { label: metricNames[2], value: rows.value.filter((row) => row.status === statuses[statuses.length - 1]).length },
])

async function reloadLedger() {
  try {
    const [ledgerResponse, readbackResponse, profileResponse] = await Promise.all([
      request(`${ENDPOINT}/ledger/list`),
      request(`${ENDPOINT}/ledger/readback`),
      request(`${ENDPOINT}/profiles/list`),
    ])
    if (!ledgerResponse.ok || !readbackResponse.ok || !profileResponse.ok) {
      throw new Error('接入档案台账读取失败')
    }
    ledger.value = (await ledgerResponse.json()).items ?? []
    readbacks.value = (await readbackResponse.json()).items ?? []
    profiles.value = (await profileResponse.json()).items ?? []
  } catch (error) {
    ledgerMessage.value = error instanceof Error ? error.message : '接入档案台账读取失败'
  }
}

async function confirmLedger(row: LedgerRow) {
  ledgerMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/ledger/${row.id}/confirm`, {
      method: 'POST',
      body: JSON.stringify({ expected_version: row.档案版本 }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '台账确认失败')
    ledgerMessage.value = payload.message
    await reloadLedger()
  } catch (error) {
    ledgerMessage.value = error instanceof Error ? error.message : '台账确认失败'
  }
}

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value).toString()
  try {
    const response = await request(`${ENDPOINT}/export?${query}`)
    if (!response.ok) throw new Error('导出失败，请稍后重试')
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = 'auth.csv'
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(columns.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST', body: JSON.stringify(createValues.value),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '登记失败')
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('凭证管理动作未生效，请稍后重试')
    }
    const payload = await response.json()
    if (!payload.ok) throw new Error(payload.message || '凭证管理动作未生效')
    ledgerMessage.value = payload.message
    await reload()
    await reloadLedger()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '凭证管理操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('认证凭证列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '凭证管理列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void reloadLedger()
})
</script>
