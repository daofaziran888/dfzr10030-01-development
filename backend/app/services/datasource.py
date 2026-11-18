"""数据源配置业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.services.access_profile import access_profile_service
from app.store import store

MODULE = "datasource"
LIST_FIELDS = ["源端编号", "连接类型", "接入地址", "认证方式", "采样周期", "超时秒数", "重试上限", "负责人"]
REQUIRED_FIELDS = ["源端编号", "连接类型", "接入地址"]
STATUS_ORDER = ["草稿", "待校验", "已启用", "已停用"]
ACTION_RULES = {"提交校验": "待校验", "启用配置": "已启用", "停用配置": "已停用"}
NEGATIVE_ACTIONS = ["停用配置"]


class DatasourceService:
    def __init__(self) -> None:
        # 数据源页是接入档案的主入口：按源端编号解析连接与认证字段。
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
            rows = [row for row in rows if keyword.casefold() in str(row.get("源端编号", "")).casefold()]
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
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"数据源 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于数据源配置可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        # 状态变化会改变可用性，档案随之重算，但旧依据保留在历史里。
        profile, _ = self.profiles.generate(entry_id, reason=f"数据源{action}")
        message = f"数据源已{action}"
        if profile is not None:
            message += f"；接入档案{profile['可用状态']}"
        return entry, message

    def access_profiles(self) -> list[dict[str, Any]]:
        """数据源页读取的接入档案：每个源端只暴露一份当前快照。"""
        return self.profiles.list_profiles()

    def access_profile(self, entry_id: int) -> dict[str, Any] | None:
        return self.profiles.get_profile(entry_id)

    def profile_history(self, entry_id: int) -> list[dict[str, Any]] | None:
        return self.profiles.history(entry_id)

    def build_profile(
        self,
        entry_id: int,
        *,
        expected_version: int | None = None,
        conflict_policy: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        return self.profiles.generate(
            entry_id, expected_version=expected_version, conflict_policy=conflict_policy
        )

    def revalidate(self, entry_id: int) -> tuple[dict[str, Any] | None, str]:
        return self.profiles.revalidate(entry_id)

    def resolve_conflict(
        self, entry_id: int, policy: str
    ) -> tuple[dict[str, Any] | None, str]:
        return self.profiles.resolve_conflict(entry_id, policy)

    def executable_profiles(self) -> list[dict[str, Any]]:
        return self.profiles.executable_profiles()
