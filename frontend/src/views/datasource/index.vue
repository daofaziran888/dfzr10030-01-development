<template>
  <section class="page" data-module="datasource">
    <header class="page-head">
      <div>
        <h2>数据源配置管理</h2>
        <p class="page-desc">维护数据源，围绕源端编号、连接类型、接入地址、认证方式做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">登记数据源</button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">导出数据源配置清单</button>
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
          <td :colspan="columns.length + 1" class="empty-state">暂无数据源配置数据，可先登记数据源</td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记数据源</h3>
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
      <span>共 {{ total }} 条数据源配置记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <section class="panel" data-testid="profile-panel">
      <header class="panel-head">
        <div>
          <h3>源端接入档案</h3>
          <p class="page-desc">
            按源端编号合并连接参数、认证凭据与最近校验结果，每个源端只保留一份当前可用的配置快照。
          </p>
        </div>
        <div class="panel-meta">
          <span class="badge" data-testid="executable-count">可执行清单 {{ executableProfiles.length }} 份</span>
          <button class="btn" data-testid="refresh-profiles" type="button" @click="reloadProfiles">
            刷新档案
          </button>
        </div>
      </header>

      <p v-if="profileMessage" class="panel-message" data-testid="profile-message">{{ profileMessage }}</p>

      <div class="profile-list" role="table" aria-label="源端接入档案">
        <div class="profile-row profile-row-10 profile-head" role="row">
          <span>源端编号</span>
          <span>凭据版本</span>
          <span>接入地址</span>
          <span>校验结果</span>
          <span>可用状态</span>
          <span>冲突状态</span>
          <span>当前批次</span>
          <span>历史依据</span>
          <span>失败原因</span>
          <span>可执行动作</span>
        </div>
        <div
          v-for="profile in profiles"
          :key="String(profile.档案编号)"
          class="profile-row profile-row-10"
          role="row"
          :data-testid="`profile-${profile.源端编号}`"
          :data-availability="String(profile.可用状态)"
        >
          <span>{{ profile.源端编号 }}</span>
          <span>{{ profile.凭据版本 }}</span>
          <span class="cell-wrap">{{ profile.接入地址 }}</span>
          <span>{{ profile.校验结果 }}</span>
          <span>
            <span class="badge" :class="`badge-${profile.可用状态}`">{{ profile.可用状态 }}</span>
          </span>
          <span>{{ profile.冲突状态 }}</span>
          <span class="cell-wrap">{{ profile.当前批次 || '—' }}</span>
          <span>{{ profile.历史依据数 }}</span>
          <span class="cell-wrap error-text">{{ profile.失败原因 || '—' }}</span>
          <span class="row-actions">
            <button
              class="link"
              type="button"
              :data-testid="`build-${profile.源端编号}`"
              @click="buildProfile(profile)"
            >
              生成档案
            </button>
            <button
              class="link"
              type="button"
              :data-testid="`revalidate-${profile.源端编号}`"
              @click="revalidateProfile(profile)"
            >
              重新校验
            </button>
            <button
              class="link"
              type="button"
              :data-testid="`history-${profile.源端编号}`"
              @click="openHistory(profile)"
            >
              历史依据
            </button>
            <select
              v-if="profile.冲突状态 === '待处理'"
              class="conflict-select"
              :data-testid="`policy-${profile.源端编号}`"
              :value="policyDraft[String(profile.源端编号)] || '续期优先'"
              @change="onPolicyChange(profile, $event)"
            >
              <option value="续期优先">续期优先</option>
              <option value="地址优先">地址优先</option>
            </select>
            <button
              v-if="profile.冲突状态 === '待处理'"
              class="link"
              type="button"
              :data-testid="`resolve-${profile.源端编号}`"
              @click="resolveConflict(profile)"
            >
              按口径重算
            </button>
          </span>
        </div>
        <p v-if="!profiles.length" class="empty-state">暂无源端接入档案</p>
      </div>

      <p class="page-desc" data-testid="executable-list">
        可执行清单：{{ executableProfiles.map((item) => item.源端编号).join('、') || '暂无' }}
      </p>
      <p class="page-desc">
        阈值口径：超时 1-300 秒、重试 0-10 次；校验未通过或凭据不可用的源端不会进入可执行清单。
      </p>
    </section>

    <div v-if="historyProfile" class="modal-backdrop" data-testid="history-modal">
      <div class="modal">
        <h3>历史依据 · {{ historyProfile.源端编号 }}</h3>
        <div class="profile-list" role="table" aria-label="历史依据">
          <div class="profile-row profile-head history-row" role="row">
            <span>档案版本</span><span>凭据版本</span><span>接入地址</span><span>可用状态</span><span>冲突状态</span><span>归档时间</span>
          </div>
          <div
            v-for="item in historyRows"
            :key="String(item.档案版本) + String(item.归档时间)"
            class="profile-row history-row"
            role="row"
          >
            <span>{{ item.档案版本 }}</span>
            <span>{{ item.凭据版本 }}</span>
            <span class="cell-wrap">{{ item.接入地址 }}</span>
            <span>{{ item.可用状态 }}</span>
            <span>{{ item.冲突状态 }}</span>
            <span>{{ item.归档时间 }}</span>
          </div>
          <p v-if="!historyRows.length" class="empty-state">暂无历史依据，当前档案首次生成</p>
        </div>
        <div class="page-actions">
          <button class="btn" type="button" @click="historyProfile = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

type Profile = Record<string, string | number | boolean | null>

const ENDPOINT = '/api/datasource'
const columns = ["源端编号", "连接类型", "接入地址", "认证方式", "采样周期", "超时秒数", "重试上限", "负责人"]
const actions = ["提交校验", "启用配置", "停用配置"]
const statuses = ["草稿", "待校验", "已启用", "已停用"]
const metricNames = ["数据源总数", "已启用数据源", "待校验数据源"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
const profiles = ref<Profile[]>([])
const executableProfiles = ref<Profile[]>([])
const profileMessage = ref('')
const historyProfile = ref<Profile | null>(null)
const historyRows = ref<Profile[]>([])
const policyDraft = ref<Record<string, string>>({})
const stats = computed(() => [
  { label: metricNames[0], value: total.value },
  { label: metricNames[1], value: rows.value.filter((row) => row.status === statuses[1]).length },
  { label: metricNames[2], value: rows.value.filter((row) => row.status === statuses[statuses.length - 1]).length },
])

async function reloadProfiles() {
  try {
    const [listResponse, executableResponse] = await Promise.all([
      request(`${ENDPOINT}/profiles/list`),
      request(`${ENDPOINT}/profiles/executable`),
    ])
    if (!listResponse.ok || !executableResponse.ok) throw new Error('接入档案读取失败')
    const listPayload = await listResponse.json()
    const executablePayload = await executableResponse.json()
    profiles.value = listPayload.items ?? []
    executableProfiles.value = executablePayload.items ?? []
  } catch (error) {
    profileMessage.value = error instanceof Error ? error.message : '接入档案读取失败'
  }
}

async function postProfile(path: string, body: Record<string, unknown>) {
  const response = await request(`${ENDPOINT}${path}`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  const payload = await response.json()
  if (!response.ok || !payload.ok) throw new Error(payload.message || '接入档案写入失败')
  profileMessage.value = payload.message
  await reloadProfiles()
}

async function buildProfile(profile: Profile) {
  profileMessage.value = ''
  try {
    // 携带当前档案版本：并发生成时只有一次生效，后到的请求会被拒绝。
    await postProfile(`/${profile.id}/profile`, { expected_version: profile.档案版本 })
  } catch (error) {
    profileMessage.value = error instanceof Error ? error.message : '接入档案生成失败'
  }
}

async function revalidateProfile(profile: Profile) {
  profileMessage.value = ''
  try {
    await postProfile(`/${profile.id}/profile/revalidate`, {})
  } catch (error) {
    profileMessage.value = error instanceof Error ? error.message : '重新校验失败'
  }
}

function onPolicyChange(profile: Profile, event: Event) {
  policyDraft.value[String(profile.源端编号)] = (event.target as HTMLSelectElement).value
}

async function resolveConflict(profile: Profile) {
  profileMessage.value = ''
  const policy = policyDraft.value[String(profile.源端编号)] || '续期优先'
  try {
    await postProfile(`/${profile.id}/profile/conflict`, { policy })
  } catch (error) {
    profileMessage.value = error instanceof Error ? error.message : '冲突取舍失败'
  }
}

async function openHistory(profile: Profile) {
  historyProfile.value = profile
  historyRows.value = []
  try {
    const response = await request(`${ENDPOINT}/${profile.id}/profile/history`)
    if (!response.ok) throw new Error('历史依据读取失败')
    const payload = await response.json()
    historyRows.value = payload.items ?? []
  } catch (error) {
    profileMessage.value = error instanceof Error ? error.message : '历史依据读取失败'
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
    link.download = 'datasource.csv'
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
      throw new Error('数据源配置动作未生效，请稍后重试')
    }
    const payload = await response.json()
    if (!payload.ok) throw new Error(payload.message || '数据源配置动作未生效')
    profileMessage.value = payload.message
    await reload()
    await reloadProfiles()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据源配置操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('数据源列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据源配置列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void reloadProfiles()
})
</script>
