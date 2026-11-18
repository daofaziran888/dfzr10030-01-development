# 多源数据采集与RPA自动化平台

面向网页抓取、API接入、增量采集、RPA流程编排、数据校验与采集监控的数据工程平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 数据源配置 | `datasource` | 数据源 | 源端编号、连接类型、接入地址 |
| 网页采集规则 | `crawler` | 采集规则 | 规则编号、目标网址、页面选择器 |
| API接入管理 | `apiclient` | API客户端 | 客户端编号、接口名称、请求方法 |
| 增量采集 | `incremental` | 增量游标 | 游标编号、来源标识、增量字段 |
| RPA任务编排 | `robot_task` | RPA任务 | 任务编号、任务名称、页面定位器 |
| 数据接入通道 | `ingestion` | 接入通道 | 通道编号、通道名称、输入格式 |
| 格式解析器 | `parser` | 解析配置 | 解析编号、输入格式、输出格式 |
| 采集结果校验 | `validator` | 校验规则 | 规则编号、校验字段、校验类型 |
| 采集去重 | `dedup` | 去重策略 | 策略编号、输入来源、去重键 |
| 采集调度 | `schedule` | 调度计划 | 计划编号、关联任务、调度周期 |
| 采集监控 | `monitor` | 监控面板 | 面板编号、采集源总数、今日采集量 |
| 采集日志 | `log_viewer` | 日志条目 | 日志编号、关联任务、日志级别 |
| 凭证管理 | `auth` | 认证凭证 | 凭证编号、凭证类型、关联数据源 |
| 采集转换管道 | `transform` | 转换节点 | 节点编号、输入来源、输出目标 |
| 数据流转编排 | `flow` | 流转管道 | 管道编号、管道名称、起始节点 |
| 数据血缘追踪 | `lineage` | 血缘关系 | 关系编号、上游节点、下游节点 |
| 采集报告 | `report` | 采集报告 | 报告编号、采集源、统计周期 |
| 源端接入档案 | `access_profile`（服务层） | 接入档案 | 源端编号、凭据版本、接入地址、可用状态 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 源端接入档案

把「数据源配置的连接参数」「认证凭据」「最近校验结果」合并成每个源端唯一的一份
可执行接入档案，规则集中在 `backend/app/services/access_profile.py`。

- 合并口径：按源端编号解析连接字段，取该源端最近续期的可用凭据；`凭据版本`与
  `接入地址` 始终来自同一份配置快照，档案里保留 `配置快照` 标识。
- 阈值与规则：超时 1-300 秒、重试 0-10 次、每源端仅 1 份可执行档案、历史依据最多
  保留 20 份；超出范围或上限的记录会在 `失败原因` / `口径说明` 里写明原因。
- 可执行清单：校验未通过、凭据不可用或数据源未启用的源端不会进入清单，避免采集
  任务继续向旧端点写入数据。
- 冲突边界：续期回执与旧接入地址的失败校验结果同时落在同一源端时，按
  `续期优先` 或 `地址优先` 取舍；两种口径都保持业务结果，旧依据保留在历史里。
- 并发写入：生成档案与确认台账都带 `expected_version`，先到的一次生效，后到的
  请求被拒绝并说明当前版本。

| 接口 | 说明 |
| --- | --- |
| `GET /api/datasource/profiles/list` | 每个源端当前的接入档案 |
| `GET /api/datasource/profiles/executable` | 可执行清单 |
| `GET /api/datasource/{id}/profile` | 按源端编号/ID 解析出的接入档案 |
| `GET /api/datasource/{id}/profile/history` | 历史依据（旧档案快照） |
| `POST /api/datasource/{id}/profile` | 生成档案，支持 `expected_version`、`conflict_policy` |
| `POST /api/datasource/{id}/profile/revalidate` | 重新校验并更新档案 |
| `POST /api/datasource/{id}/profile/conflict` | 按 `续期优先`/`地址优先` 重算 |
| `GET /api/auth/profiles/list` | 认证页只读读取接入档案 |
| `GET /api/auth/ledger/list` | 接入档案落入的待确认台账 |
| `POST /api/auth/ledger/{id}/confirm` | 确认入账并生成回读记录 |
| `GET /api/auth/ledger/readback` | 可回读记录 |
| `GET /api/auth/verify/results` | 认证服务返回给数据源配置的核对结果 |

认证服务在 `续期凭证` / `吊销凭证` 时回写档案的凭据版本与可用性：续期会阻断旧凭据
并登记续期回执，吊销会让该源端档案立即退出可执行清单。


领域：数据工程
子方向：数据采集、爬虫与RPA
