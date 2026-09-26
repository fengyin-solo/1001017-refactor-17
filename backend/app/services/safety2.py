"""交安设施业务规则：状态流转、字段校验与筛选口径都收在这里。

在役/可养护判断不在本文件另写，统一调用 app.services.safety_status，
台账、详情与养护记录登记共用同一份口径。
"""
from __future__ import annotations

from typing import Any

from app.services import safety_status
from app.store import store

MODULE = "safety2"
REQUIRED_FIELDS = ["设施编号", "设施类型", "所在路段"]
STATUS_ORDER = ["完好", "损坏", "维修中", "已更换"]
ACTION_RULES = {"登记损坏": "损坏", "安排维修": "维修中", "完成更换": "已更换"}
NEGATIVE_ACTIONS = []


class Safety2Service:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("设施编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = rows[start:start + size]
        # 台账展示结论与详情、养护登记同源，避免各写一套
        return [safety_status.annotate(row) for row in page_rows], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return safety_status.annotate(entry)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"交安设施 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于交安设施可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        # 安排维修同样以统一在役口径为准，已拆除等设施不再派养护
        if action == "安排维修":
            verdict = safety_status.judge_entry(entry)
            if not verdict.serviceable:
                return None, verdict.reason
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        safety_status.annotate(entry)
        return entry, f"交安设施已{action}"
