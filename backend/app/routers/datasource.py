"""数据源配置接口：维护数据源，覆盖提交校验、启用配置、停用配置等动作。"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.schemas import (
    ActionPayload,
    ActionResult,
    ConflictResolvePayload,
    EntryPayload,
    PageResult,
    ProfileBuildPayload,
)
from app.services.datasource import DatasourceService

router = APIRouter(prefix="/api/datasource", tags=["数据源配置"])
service = DatasourceService()

LIST_FIELDS = ["源端编号", "连接类型", "接入地址", "认证方式", "采样周期", "超时秒数", "重试上限", "负责人"]
STATUSES = ["草稿", "待校验", "已启用", "已停用"]


def query_filters(request: Request) -> dict[str, str]:
    """只接受当前模块声明过的字段，忽略分页等保留参数。"""
    return {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in LIST_FIELDS and value.strip()
    }


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按源端编号检索"),
    status: str | None = Query(default=None, description="草稿、待校验、已启用、已停用"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    """按页面字段、源端编号关键字与状态过滤数据源配置列表。"""
    items, total = service.list_entries(
        filters=query_filters(request), keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries(
    request: Request,
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> StreamingResponse:
    """下载当前筛选条件下的 UTF-8 CSV；必须声明在 /{entry_id} 之前。"""
    items, _ = service.list_entries(
        filters=query_filters(request), keyword=keyword, status=status, page=1, size=1000000)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["id", *LIST_FIELDS, "status"])
    for item in items:
        row = []
        for value in [item.get("id"), *(item.get(field, "") for field in LIST_FIELDS), item.get("status", "")]:
            text = "" if value is None else str(value)
            row.append("'" + text if text.startswith(("=", "+", "-", "@")) else text)
        writer.writerow(row)
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="datasource.csv"'})


@router.get("/profiles/list")
def list_profiles() -> dict[str, object]:
    """读取每个源端当前唯一的一份接入档案（含不可执行的失败原因）。"""
    items = service.access_profiles()
    return {"items": items, "total": len(items)}


@router.get("/profiles/executable")
def list_executable_profiles() -> dict[str, object]:
    """可执行清单：校验未通过或凭据不可用的源端不会出现在这里。"""
    items = service.executable_profiles()
    return {"items": items, "total": len(items)}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条数据源明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"数据源 {entry_id} 不存在或已归档")
    return entry


@router.get("/{entry_id}/profile")
def get_profile(entry_id: int) -> dict:
    """按源端编号解析连接与认证字段，返回该源端的接入档案。"""
    profile = service.access_profile(entry_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"数据源 {entry_id} 不存在或已归档")
    return profile


@router.get("/{entry_id}/profile/history")
def get_profile_history(entry_id: int) -> dict[str, object]:
    """历史依据：每次重算前的旧档案快照，最新在前。"""
    history = service.profile_history(entry_id)
    if history is None:
        raise HTTPException(status_code=404, detail=f"数据源 {entry_id} 不存在或已归档")
    return {"items": history, "total": len(history)}


@router.post("/{entry_id}/profile", response_model=ActionResult)
def build_profile(entry_id: int, payload: ProfileBuildPayload) -> ActionResult:
    """生成源端接入档案；expected_version 不一致时拒绝后到的并发写入。"""
    profile, message = service.build_profile(
        entry_id,
        expected_version=payload.expected_version,
        conflict_policy=payload.conflict_policy,
    )
    if profile is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=profile)


@router.post("/{entry_id}/profile/revalidate", response_model=ActionResult)
def revalidate_profile(entry_id: int) -> ActionResult:
    """重新校验并更新接入档案，可执行清单随之变化。"""
    profile, message = service.revalidate(entry_id)
    if profile is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=profile)


@router.post("/{entry_id}/profile/conflict", response_model=ActionResult)
def resolve_conflict(entry_id: int, payload: ConflictResolvePayload) -> ActionResult:
    """在续期优先/地址优先两个边界里取舍，按冲突口径重算档案并保留旧依据。"""
    profile, message = service.resolve_conflict(entry_id, payload.policy.strip())
    if profile is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=profile)


@router.post("", response_model=ActionResult)
def create_entry(payload: dict[str, object]) -> ActionResult:
    """登记一条数据源，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="数据源已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: ActionPayload) -> ActionResult:
    """对单条数据源执行提交校验、启用配置、停用配置；不允许的动作会被拦下并说明原因。"""
    entry, message = service.run_action(entry_id, payload.action.strip())
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
