"""源端接入档案业务规则。

把「数据源配置的连接参数」「认证凭据」「最近校验结果」三份输入合并成一份
可执行的接入配置快照。每个源端只保留一份当前档案，旧档案作为历史依据保留；
校验未通过、凭据不可用或配置越界的源端不会进入可执行清单。

并发写入用档案版本号做乐观锁：两个请求携带同一个 expected_version 时，
先到的一次生效，后到的直接拒绝并说明原因。
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from app.store import store

DATASOURCE_MODULE = "datasource"
AUTH_MODULE = "auth"

USABLE_CREDENTIAL_STATUSES = ("有效", "即将过期")
CHECK_PASSED = "通过"
CHECK_FAILED = "未通过"
CHECK_PENDING = "待校验"
CHECK_MISSING = "未校验"

PROFILE_EXECUTABLE = "可执行"
PROFILE_CANDIDATE = "候选"
PROFILE_PENDING = "待验证"
PROFILE_BLOCKED = "已阻断"

CONFLICT_PENDING = "待处理"
CONFLICT_RESOLVED = "已解决"
CONFLICT_NONE = "无冲突"

CONFLICT_POLICIES = ("续期优先", "地址优先")

# 阈值、口径与规则：超出范围的记录要在档案里说明具体原因。
TIMEOUT_RANGE = (1, 300)
RETRY_RANGE = (0, 10)
MAX_USABLE_CREDENTIALS = 1
MAX_HISTORY_RECORDS = 20


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _version_number(text: Any) -> int:
    digits = "".join(ch for ch in str(text or "") if ch.isdigit())
    return int(digits) if digits else 1


class AccessProfileService:
    """源端接入档案的解析、合并、冲突处理与回读。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._profiles: dict[str, dict[str, Any]] = {}
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._trimmed: dict[str, int] = {}
        self._checks: dict[str, dict[str, Any]] = {
            "DATA-0001": {
                "校验结果": CHECK_MISSING,
                "失败原因": "尚未提交校验",
                "校验批次": "CHECK-0001",
                "校验时间": "2026-11-10 09:00:00",
            },
            "DATA-0002": {
                "校验结果": CHECK_FAILED,
                "失败原因": "旧接入地址连接超时",
                "校验批次": "CHECK-0002",
                "校验时间": "2026-11-16 10:30:00",
            },
            "DATA-0003": {
                "校验结果": CHECK_PASSED,
                "失败原因": "",
                "校验批次": "CHECK-0003",
                "校验时间": "2026-11-17 08:15:00",
            },
        }
        self._renewals: dict[str, dict[str, Any]] = {}
        self._resolutions: dict[str, dict[str, Any]] = {}
        self._ledger: dict[str, dict[str, Any]] = {}
        self._records: list[dict[str, Any]] = []
        self._ledger_seq = 0
        self._record_seq = 0
        self._receipt_seq = 0
        self._seed_conflict()

    def _seed_conflict(self) -> None:
        """示例数据：DATA-0002 刚完成续期，同时留着旧地址的失败校验结果。

        续期前的那份档案作为旧依据保留，续期后按新凭据版本重新合并一次档案，
        于是「续期回执」和「旧地址校验失败」同时落在同一源端，等待口径取舍。
        """
        datasource = self._find_datasource("DATA-0002")
        if datasource is None:
            return
        credential, _ = self._pick_credential(datasource)
        if credential is None:
            return
        self._receipt_seq += 1
        self._renewals["DATA-0002"] = {
            "回执编号": "RCVD-0001",
            "凭证编号": str(credential.get("凭证编号") or ""),
            "源端编号": "DATA-0002",
            "旧凭据版本": "v1",
            "新凭据版本": self._credential_version(credential),
            "续期时间": "2026-11-16 10:00:00",
        }
        baseline = self._compose(datasource, write_reason="续期前档案")
        baseline.update({
            "档案编号": f"PROF-{int(datasource.get('id') or 0):04d}",
            "档案版本": 1,
            "凭据版本": "v1",
            "凭据状态": "即将过期",
            "冲突状态": CONFLICT_NONE,
            "冲突口径": "",
            "当前批次": "",
            "下一批候选": "",
            "可用状态": PROFILE_EXECUTABLE,
            "是否可执行": True,
            "失败原因": "",
            "口径说明": "",
            "快照来源": "当前数据源配置",
            "生成时间": "2026-11-10 09:00:00",
        })
        baseline["配置快照"] = f"SNAP-{int(datasource.get('id') or 0):04d}-v1"
        self._remember(baseline)
        profile = self._compose(datasource, previous=baseline, write_reason="认证续期")
        self._store(profile)

    # ------------------------------------------------------------------
    # 基础数据读取
    # ------------------------------------------------------------------
    def _datasources(self) -> list[dict[str, Any]]:
        return store.rows(DATASOURCE_MODULE)

    def _credentials(self) -> list[dict[str, Any]]:
        return store.rows(AUTH_MODULE)

    def _find_datasource(self, source_ref: int | str) -> dict[str, Any] | None:
        text = str(source_ref).strip()
        for row in self._datasources():
            if str(row.get("id")) == text or str(row.get("源端编号") or "").strip() == text:
                return row
        return None

    def _source_code(self, datasource: dict[str, Any]) -> str:
        return str(datasource.get("源端编号") or f"DATA-{datasource.get('id')}").strip()

    def _credentials_for(self, datasource: dict[str, Any]) -> list[dict[str, Any]]:
        source = self._source_code(datasource)
        source_id = str(datasource.get("id"))
        matched: list[dict[str, Any]] = []
        for row in self._credentials():
            linked = str(row.get("关联数据源") or "").strip()
            if linked in (source, source_id):
                matched.append(row)
        return matched

    def _pick_credential(self, datasource: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        matched = self._credentials_for(datasource)
        usable = [row for row in matched if str(row.get("status") or "") in USABLE_CREDENTIAL_STATUSES]
        if usable:
            usable.sort(
                key=lambda row: (_version_number(row.get("凭据版本")), int(row.get("id") or 0)),
                reverse=True,
            )
            return usable[0], matched
        if matched:
            matched.sort(key=lambda row: int(row.get("id") or 0), reverse=True)
            return matched[0], matched
        return None, matched

    def _check_for(self, source: str) -> dict[str, Any]:
        return self._checks.setdefault(source, {
            "校验结果": CHECK_MISSING,
            "失败原因": "尚未提交校验",
            "校验批次": "—",
            "校验时间": "—",
        })

    def _credential_version(self, credential: dict[str, Any]) -> str:
        return str(credential.get("凭据版本") or "v1").strip()

    # ------------------------------------------------------------------
    # 阈值与规则
    # ------------------------------------------------------------------
    def _config_reasons(self, datasource: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        timeout = _to_int(datasource.get("超时秒数"))
        if timeout is None:
            reasons.append(f"超时秒数「{datasource.get('超时秒数') or ''}」不是有效整数")
        elif not TIMEOUT_RANGE[0] <= timeout <= TIMEOUT_RANGE[1]:
            reasons.append(
                f"超时秒数 {timeout} 超出允许范围 {TIMEOUT_RANGE[0]}-{TIMEOUT_RANGE[1]} 秒"
            )
        retries = _to_int(datasource.get("重试上限"))
        if retries is None:
            reasons.append(f"重试上限「{datasource.get('重试上限') or ''}」不是有效整数")
        elif not RETRY_RANGE[0] <= retries <= RETRY_RANGE[1]:
            reasons.append(
                f"重试上限 {retries} 超出允许范围 {RETRY_RANGE[0]}-{RETRY_RANGE[1]} 次"
            )
        address = str(datasource.get("接入地址") or "").strip()
        if not address:
            reasons.append("接入地址为空")
        elif not address.startswith(("http://", "https://", "jdbc:", "ftp://")):
            reasons.append(f"接入地址「{address}」不是可用的连接地址")
        if not str(datasource.get("认证方式") or "").strip():
            reasons.append("认证方式为空")
        return reasons

    def _pinned_snapshot(
        self, source: str, previous: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """地址优先时取续期前那一份快照：地址与凭据版本必须同源。"""
        receipt = self._renewals.get(source) or {}
        old_version = str(receipt.get("旧凭据版本") or "")
        for snapshot in reversed(self._history.get(source, [])):
            if str(snapshot.get("凭据版本") or "") == old_version:
                return snapshot
        if previous is not None and str(previous.get("凭据版本") or "") == old_version:
            return previous
        return previous

    # ------------------------------------------------------------------
    # 档案合并
    # ------------------------------------------------------------------
    def _compose(
        self,
        datasource: dict[str, Any],
        *,
        previous: dict[str, Any] | None = None,
        conflict_policy: str | None = None,
        pin_previous_snapshot: bool = False,
        write_reason: str = "档案生成",
    ) -> dict[str, Any]:
        source = self._source_code(datasource)
        check = self._check_for(source)
        credential, matched = self._pick_credential(datasource)

        reasons = self._config_reasons(datasource)
        notes: list[str] = []

        if credential is None:
            reasons.append("缺少与该源端关联的认证凭据")
            cred_status = "无"
            cred_version = "—"
            credential_id = "—"
            credential_label = "—"
        else:
            cred_status = str(credential.get("status") or "")
            cred_version = self._credential_version(credential)
            credential_id = str(credential.get("凭证编号") or "—")
            credential_label = (
                f"{credential_id}（{credential.get('凭证类型') or '未知类型'}，{cred_version}）"
            )
            if cred_status not in USABLE_CREDENTIAL_STATUSES:
                reasons.append(f"认证凭据 {credential_id} 当前状态为{cred_status}，不可用于接入")

        usable = [row for row in matched if str(row.get("status") or "") in USABLE_CREDENTIAL_STATUSES]
        if len(usable) > MAX_USABLE_CREDENTIALS:
            notes.append(
                f"同一源端存在 {len(usable)} 份可用凭据，超过上限 "
                f"{MAX_USABLE_CREDENTIALS} 份，仅引用最近续期的一份"
            )

        trimmed = self._trimmed.get(source)
        if trimmed:
            notes.append(
                f"历史依据超过上限 {MAX_HISTORY_RECORDS} 份，已清理 {trimmed} 份最旧记录"
            )

        validation = str(check.get("校验结果") or CHECK_MISSING)
        if validation == CHECK_FAILED:
            reasons.append(f"最近校验未通过：{check.get('失败原因') or '未提供失败原因'}")
        elif validation in (CHECK_PENDING, CHECK_MISSING):
            reasons.append(f"最近校验结果为{validation}，尚未取得通过结论")

        status = str(datasource.get("status") or "")
        if status != "已启用":
            reasons.append(f"数据源状态为{status or '未知'}，未启用")

        address = str(datasource.get("接入地址") or "").strip() or "—"
        snapshot_source = "当前数据源配置"
        old_version = str(previous.get("凭据版本") or "") if previous else ""
        old_address = str(previous.get("接入地址") or "") if previous else ""

        receipt = self._renewals.get(source)
        resolution = self._resolutions.get(source)
        conflict_active = bool(receipt) and validation == CHECK_FAILED
        conflict_state = CONFLICT_NONE
        current_batch = ""
        next_candidate = ""
        if conflict_active:
            if resolution is not None and resolution.get("回执编号") == receipt.get("回执编号"):
                # 已经取舍过，按同一口径继续重算，不再退回待处理。
                conflict_state = CONFLICT_RESOLVED
                conflict_policy = str(resolution.get("口径"))
                notes.append(f"已按「{conflict_policy}」口径重算档案，旧依据保留在历史中")
            else:
                conflict_state = CONFLICT_PENDING
                notes.append(
                    f"续期回执 {receipt.get('回执编号')}（{receipt.get('旧凭据版本')}→"
                    f"{receipt.get('新凭据版本')}）与旧接入地址的失败校验结果同时落在源端 "
                    f"{source}，需按冲突口径取舍"
                )
                current_batch = "当前批次待取舍"
                next_candidate = f"{credential_id}（{receipt.get('新凭据版本')}）"
        elif resolution is not None or conflict_policy:
            # 校验恢复通过后冲突不再成立，只保留口径说明，不再沿用旧快照。
            conflict_state = CONFLICT_RESOLVED
            conflict_policy = str(
                conflict_policy or (resolution or {}).get("口径") or ""
            )
            notes.append(f"冲突已按「{conflict_policy}」口径处理，旧依据保留在历史中")
        elif previous is not None and previous.get("冲突状态") == CONFLICT_RESOLVED:
            conflict_state = CONFLICT_RESOLVED
            conflict_policy = str(previous.get("冲突口径") or "")

        if conflict_active and conflict_policy == "地址优先":
            # 地址优先：当前批次沿用续期前的地址，凭据版本必须同一份配置。
            pin_previous_snapshot = self._pinned_snapshot(source, previous) is not None

        if pin_previous_snapshot and previous is not None:
            pinned = self._pinned_snapshot(source, previous) or previous
            address = str(pinned.get("接入地址") or address)
            cred_version = str(pinned.get("凭据版本") or cred_version)
            credential_id = str(pinned.get("凭证编号") or credential_id)
            cred_status = str(pinned.get("凭据状态") or cred_status)
            credential_label = f"{credential_id}（{cred_status}，{cred_version}）"
            snapshot_source = "上一份档案快照"

        if conflict_active:
            if conflict_policy == "续期优先":
                current_batch = "旧地址当前批次暂缓执行"
                next_candidate = f"{credential_id}（{cred_version}）进入待验证档案"
            elif conflict_policy == "地址优先":
                current_batch = "沿用续期前的接入地址完成当前批次"
                next_candidate = (
                    f"{credential_id}（{receipt.get('新凭据版本')}）进入下一批候选队列"
                    if receipt else f"{credential_id}（{cred_version}）进入下一批候选队列"
                )

        executable = not reasons and conflict_state != CONFLICT_PENDING and credential is not None
        if executable:
            availability = PROFILE_EXECUTABLE
        elif conflict_state == CONFLICT_PENDING:
            availability = PROFILE_PENDING
        elif validation in (CHECK_PENDING, CHECK_MISSING) and credential is not None:
            availability = PROFILE_CANDIDATE
        else:
            availability = PROFILE_BLOCKED

        source_id = int(datasource.get("id") or 0)
        profile_id = str(previous.get("档案编号")) if previous else f"PROF-{source_id:04d}"
        version = int(previous.get("档案版本") or 1) + 1 if previous else 1

        return {
            "id": source_id,
            "档案编号": profile_id,
            "源端编号": source,
            "连接类型": datasource.get("连接类型") or "—",
            "接入地址": address,
            "认证方式": datasource.get("认证方式") or "—",
            "凭证编号": credential_id,
            "凭据版本": cred_version,
            "凭据状态": cred_status,
            "当前凭据": credential_label,
            "校验结果": validation,
            "校验批次": check.get("校验批次") or "—",
            "校验时间": check.get("校验时间") or "—",
            "失败原因": "；".join(reasons),
            "口径说明": "；".join(notes),
            "可用状态": availability,
            "是否可执行": executable,
            "冲突状态": conflict_state,
            "冲突口径": conflict_policy or "",
            "当前批次": current_batch,
            "下一批候选": next_candidate,
            "旧凭据版本": old_version,
            "旧接入地址": old_address,
            "快照来源": snapshot_source,
            "配置快照": f"SNAP-{source_id:04d}-{cred_version}",
            "档案版本": version,
            "历史依据数": len(self._history.get(source, [])),
            "写入依据": write_reason,
            "生成时间": previous.get("生成时间") if previous else _now(),
            "更新时间": _now(),
            "阈值口径": (
                f"超时 {TIMEOUT_RANGE[0]}-{TIMEOUT_RANGE[1]} 秒；"
                f"重试 {RETRY_RANGE[0]}-{RETRY_RANGE[1]} 次；"
                f"每源端仅 {MAX_USABLE_CREDENTIALS} 份可执行档案"
            ),
        }

    def _remember(self, profile: dict[str, Any]) -> None:
        source = str(profile.get("源端编号"))
        history = self._history.setdefault(source, [])
        snapshot = dict(profile)
        snapshot["归档时间"] = _now()
        history.append(snapshot)
        if len(history) > MAX_HISTORY_RECORDS:
            overflow = len(history) - MAX_HISTORY_RECORDS
            del history[:overflow]
            self._trimmed[source] = self._trimmed.get(source, 0) + overflow
        profile["历史依据数"] = len(history)

    def _store(self, profile: dict[str, Any]) -> None:
        self._profiles[str(profile.get("源端编号"))] = profile
        self._sync_ledger(profile)

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    def get_profile(self, source_ref: int | str) -> dict[str, Any] | None:
        datasource = self._find_datasource(source_ref)
        if datasource is None:
            return None
        source = self._source_code(datasource)
        with self._lock:
            profile = self._profiles.get(source)
            if profile is None:
                profile = self._compose(datasource, write_reason="数据源读取")
                self._profiles[source] = profile
            return dict(profile)

    def list_profiles(self) -> list[dict[str, Any]]:
        with self._lock:
            for datasource in self._datasources():
                source = self._source_code(datasource)
                if source not in self._profiles:
                    self._profiles[source] = self._compose(datasource, write_reason="数据源读取")
            return [dict(self._profiles[key]) for key in sorted(self._profiles)]

    def executable_profiles(self) -> list[dict[str, Any]]:
        return [profile for profile in self.list_profiles() if profile.get("是否可执行")]

    def history(self, source_ref: int | str) -> list[dict[str, Any]] | None:
        datasource = self._find_datasource(source_ref)
        if datasource is None:
            return None
        with self._lock:
            return [dict(row) for row in reversed(self._history.get(self._source_code(datasource), []))]

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    def generate(
        self,
        source_ref: int | str,
        *,
        expected_version: int | None = None,
        conflict_policy: str | None = None,
        reason: str = "档案生成",
    ) -> tuple[dict[str, Any] | None, str]:
        datasource = self._find_datasource(source_ref)
        if datasource is None:
            return None, f"数据源 {source_ref} 不存在或已归档"
        if conflict_policy is not None and conflict_policy not in CONFLICT_POLICIES:
            return None, f"冲突口径「{conflict_policy}」不在允许范围：{'、'.join(CONFLICT_POLICIES)}"
        source = self._source_code(datasource)
        with self._lock:
            previous = self._profiles.get(source)
            current_version = int(previous.get("档案版本") or 0) if previous else 0
            if expected_version is not None and int(expected_version) != current_version:
                return None, (
                    f"并发写入冲突：源端 {source} 当前档案版本为 {current_version}，"
                    f"请求携带 {expected_version}，后到请求已拒绝"
                )
            if previous is not None:
                self._remember(previous)
            profile = self._compose(
                datasource,
                previous=previous,
                conflict_policy=conflict_policy,
                write_reason=reason,
            )
            self._store(profile)
            return dict(profile), f"源端 {source} 接入档案已生成（{profile['可用状态']}）"

    def revalidate(self, source_ref: int | str) -> tuple[dict[str, Any] | None, str]:
        datasource = self._find_datasource(source_ref)
        if datasource is None:
            return None, f"数据源 {source_ref} 不存在或已归档"
        source = self._source_code(datasource)
        with self._lock:
            credential, _ = self._pick_credential(datasource)
            config_reasons = self._config_reasons(datasource)
            cred_ok = (
                credential is not None
                and str(credential.get("status") or "") in USABLE_CREDENTIAL_STATUSES
            )
            if str(datasource.get("status") or "") == "已启用" and not config_reasons and cred_ok:
                self._checks[source] = {
                    "校验结果": CHECK_PASSED,
                    "失败原因": "",
                    "校验批次": f"CHECK-R{int(datasource.get('id') or 0):04d}",
                    "校验时间": _now(),
                }
            else:
                reasons = list(config_reasons)
                if str(datasource.get("status") or "") != "已启用":
                    reasons.append(f"数据源状态为{datasource.get('status') or '未知'}，未启用")
                if not cred_ok:
                    reasons.append("没有可用的认证凭据")
                self._checks[source] = {
                    "校验结果": CHECK_FAILED,
                    "失败原因": "；".join(reasons) or "校验未通过",
                    "校验批次": f"CHECK-R{int(datasource.get('id') or 0):04d}",
                    "校验时间": _now(),
                }
            previous = self._profiles.get(source)
            if previous is not None:
                self._remember(previous)
            profile = self._compose(datasource, previous=previous, write_reason="重新校验")
            self._store(profile)
            return dict(profile), f"源端 {source} 已重新校验：{profile['校验结果']}"

    def resolve_conflict(
        self, source_ref: int | str, policy: str
    ) -> tuple[dict[str, Any] | None, str]:
        if policy not in CONFLICT_POLICIES:
            return None, f"冲突口径「{policy}」不在允许范围：{'、'.join(CONFLICT_POLICIES)}"
        datasource = self._find_datasource(source_ref)
        if datasource is None:
            return None, f"数据源 {source_ref} 不存在或已归档"
        source = self._source_code(datasource)
        with self._lock:
            previous = self._profiles.get(source)
            if previous is None:
                return None, f"源端 {source} 尚无接入档案，请先生成档案"
            if previous.get("冲突状态") != CONFLICT_PENDING:
                return None, f"源端 {source} 当前没有待处理冲突，无需按口径重算"
            self._remember(previous)
            policy_profile = self._compose(
                datasource,
                previous=previous,
                conflict_policy=policy,
                pin_previous_snapshot=policy == "地址优先",
                write_reason=f"冲突取舍：{policy}",
            )
            # 先落取舍口径，再按同一口径重算，旧依据保留在历史里。
            self._resolutions[source] = {
                "回执编号": (self._renewals.get(source) or {}).get("回执编号", ""),
                "凭证编号": policy_profile.get("凭证编号"),
                "口径": policy,
                "当前批次": policy_profile.get("当前批次"),
                "下一批候选": policy_profile.get("下一批候选"),
                "取舍时间": _now(),
            }
            policy_profile["冲突状态"] = CONFLICT_RESOLVED
            self._store(policy_profile)
            return dict(policy_profile), f"源端 {source} 已按「{policy}」口径重算接入档案"

    # ------------------------------------------------------------------
    # 认证侧回写
    # ------------------------------------------------------------------
    def apply_credential_change(self, credential: dict[str, Any], action: str) -> str:
        """认证续期/吊销后回写接入档案的凭据版本与可用性。"""
        source_ref = str(credential.get("关联数据源") or "").strip()
        datasource = self._find_datasource(source_ref)
        if datasource is None:
            return "未找到关联源端，接入档案未回写"
        source = self._source_code(datasource)
        with self._lock:
            credential_id = str(credential.get("凭证编号") or "")
            receipt_note = ""
            if action == "续期凭证":
                old_version = self._credential_version(credential)
                new_version = f"v{_version_number(old_version) + 1}"
                credential["凭据版本"] = new_version
                self._receipt_seq += 1
                self._renewals[source] = {
                    "回执编号": f"RCVD-{self._receipt_seq:04d}",
                    "凭证编号": credential_id,
                    "源端编号": source,
                    "旧凭据版本": old_version,
                    "新凭据版本": new_version,
                    "续期时间": _now(),
                }
                receipt_note = f"已阻断旧凭据 {old_version}，续期回执 {self._renewals[source]['回执编号']} 已登记"
            previous = self._profiles.get(source)
            if previous is not None and previous.get("凭证编号") not in ("—", credential_id):
                return f"源端 {source} 当前引用 {previous.get('凭证编号')}，本次变更未改写档案"
            if previous is not None:
                self._remember(previous)
            profile = self._compose(
                datasource, previous=previous, write_reason=f"认证{action}"
            )
            if action == "吊销凭证":
                profile["可用状态"] = PROFILE_BLOCKED
                profile["是否可执行"] = False
                revoke_reason = f"认证凭据 {credential_id} 已吊销，接入档案停止可用"
                profile["失败原因"] = "；".join(
                    item for item in (profile.get("失败原因"), revoke_reason) if item
                )
            self._store(profile)
            if action == "续期凭证":
                return f"{receipt_note}，接入档案已回写"
            return "接入档案可用性已回写"

    # ------------------------------------------------------------------
    # 认证侧待确认台账与回读记录
    # ------------------------------------------------------------------
    def _sync_ledger(self, profile: dict[str, Any]) -> None:
        profile_id = str(profile.get("档案编号"))
        record = self._ledger.get(profile_id)
        if record is None:
            self._ledger_seq += 1
            self._ledger[profile_id] = {
                "id": self._ledger_seq,
                "记录编号": f"LEDG-{self._ledger_seq:04d}",
                "档案编号": profile_id,
                "源端编号": profile.get("源端编号"),
                "凭证编号": profile.get("凭证编号"),
                "凭据版本": profile.get("凭据版本"),
                "可用状态": profile.get("可用状态"),
                "档案版本": profile.get("档案版本"),
                "确认状态": "待确认",
                "回读状态": "未回读",
                "入账时间": _now(),
                "确认时间": "",
            }
            return
        if record.get("确认状态") == "已确认" and record.get("档案版本") == profile.get("档案版本"):
            # 版本没变化时保留确认结果，避免回读记录被无谓地重置。
            record["可用状态"] = profile.get("可用状态")
            return
        record.update({
            "凭证编号": profile.get("凭证编号"),
            "凭据版本": profile.get("凭据版本"),
            "可用状态": profile.get("可用状态"),
            "档案版本": profile.get("档案版本"),
            "确认状态": "待确认",
            "回读状态": "未回读",
            "入账时间": _now(),
            "确认时间": "",
        })

    def ledger(self) -> list[dict[str, Any]]:
        with self._lock:
            for profile in self.list_profiles():
                self._sync_ledger(profile)
            return [dict(row) for row in sorted(self._ledger.values(), key=lambda item: int(item["id"]))]

    def readback_records(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in reversed(self._records)]

    def confirm_ledger(
        self, ledger_id: int, *, expected_version: int | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        with self._lock:
            record = next(
                (row for row in self._ledger.values() if int(row.get("id") or 0) == int(ledger_id)),
                None,
            )
            if record is None:
                return None, f"待确认记录 {ledger_id} 不存在"
            if record.get("确认状态") == "已确认":
                return None, "该接入档案已确认，重复写入已拒绝"
            if (
                expected_version is not None
                and int(expected_version) != int(record.get("档案版本") or 0)
            ):
                return None, (
                    f"并发写入冲突：记录 {record.get('记录编号')} 当前档案版本为 "
                    f"{record.get('档案版本')}，后到请求已拒绝"
                )
            record["确认状态"] = "已确认"
            record["回读状态"] = "已回读"
            record["确认时间"] = _now()
            self._record_seq += 1
            self._records.append({
                "id": self._record_seq,
                "回读编号": f"READ-{self._record_seq:04d}",
                "记录编号": record.get("记录编号"),
                "档案编号": record.get("档案编号"),
                "源端编号": record.get("源端编号"),
                "凭证编号": record.get("凭证编号"),
                "凭据版本": record.get("凭据版本"),
                "可用状态": record.get("可用状态"),
                "核对结果": "与接入档案一致",
                "回读时间": _now(),
            })
            return dict(record), "接入档案已落入确认台账，可回读"


access_profile_service = AccessProfileService()
