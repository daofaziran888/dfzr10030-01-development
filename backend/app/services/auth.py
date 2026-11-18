"""凭证管理业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.services.access_profile import access_profile_service
from app.store import store

MODULE = "auth"
LIST_FIELDS = ["凭证编号", "凭证类型", "关联数据源", "凭证内容", "有效期至", "创建时间", "最后使用", "凭证状态"]
REQUIRED_FIELDS = ["凭证编号", "凭证类型", "关联数据源"]
STATUS_ORDER = ["有效", "即将过期", "已过期", "已吊销"]
ACTION_RULES = {"续期凭证": "有效", "吊销凭证": "已吊销"}
NEGATIVE_ACTIONS = []


class AuthService:
    def __init__(self) -> None:
        self.profiles = access_profile_service

    def list_entries(
        self,
        *,
        filters: dict[str, str] | None = None,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        for field, expected in (filters or {}).items():
            rows = [row for row in rows if expected.casefold() in str(row.get(field, "")).casefold()]
        if keyword:
            rows = [row for row in rows if keyword.casefold() in str(row.get("凭证编号", "")).casefold()]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in LIST_FIELDS})
        entry["凭据版本"] = str(values.get("凭据版本") or "v1")
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"认证凭证 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于凭证管理可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        # 续期/吊销后把凭据版本与可用性回写到该源端的接入档案。
        writeback = self.profiles.apply_credential_change(entry, action)
        entry["档案回写"] = writeback
        return entry, f"认证凭证已{action}；{writeback}"

    def profiles_for_auth(self) -> list[dict[str, Any]]:
        """认证页面一并读取源端接入档案，作为只读输入展示。"""
        return self.profiles.list_profiles()

    def ledger(self) -> list[dict[str, Any]]:
        return self.profiles.ledger()

    def readback_records(self) -> list[dict[str, Any]]:
        return self.profiles.readback_records()

    def confirm_ledger(self, ledger_id: int, expected_version: int | None = None):
        return self.profiles.confirm_ledger(ledger_id, expected_version=expected_version)

    def verify_results(self) -> list[dict[str, Any]]:
        """向数据源配置返回的核对结果：只读接入档案，不改数据源本身。"""
        return [
            {
                "源端编号": profile.get("源端编号"),
                "凭证编号": profile.get("凭证编号"),
                "凭据版本": profile.get("凭据版本"),
                "可用状态": profile.get("可用状态"),
                "校验结果": profile.get("校验结果"),
                "核对结果": (
                    "一致" if profile.get("是否可执行") else "需处理"
                ),
                "失败原因": profile.get("失败原因"),
            }
            for profile in self.profiles.list_profiles()
        ]
