"""养护维修业务规则：状态流转、字段校验与筛选口径都收在这里。

面向交安设施派养护任务时，设施是否在役、可养护不在本文件判断，
统一调用 app.services.safety_status，与交安设施台账、设施详情同口径。
"""
from __future__ import annotations

from typing import Any

from app.services import safety_status
from app.store import store

MODULE = "repair"
REQUIRED_FIELDS = ["任务编号", "任务类型", "维修对象"]
STATUS_ORDER = ["待派发", "施工中", "待验收", "已竣工"]
ACTION_RULES = {"派发任务": "施工中", "开始施工": "待验收", "验收竣工": "已竣工"}
NEGATIVE_ACTIONS = []


class RepairService:
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
            rows = [row for row in rows if keyword in str(row.get("任务编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(
        self, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, list[str], str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, ""
        station = values.get(safety_status.STATION_FIELD)
        if station is not None and str(station).strip():
            # 登记交安设施养护任务：可养护与否完全以统一口径判定，
            # 台账里已拆除/不在役的设施不允许再派养护任务
            verdict = safety_status.judge_by_station(station)
            if not verdict.serviceable:
                return None, [], verdict.reason
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        if station is not None and str(station).strip():
            entry[safety_status.STATION_FIELD] = str(station).strip()
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, [], ""

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"维修任务 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于养护维修可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"维修任务已{action}"
