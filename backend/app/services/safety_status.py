"""交安设施在役（可养护）判断：全平台唯一口径。

交安设施台账、设施详情与养护记录登记校验都必须调用本模块，
不允许在各自代码里再写一遍判断。以后调整"什么情况下还算在役、
还能不能派养护任务"的口径，只改本文件这一处。

判断只依据按桩号位置从交安设施台账里取到的设施类型、设施规格与
设置日期（以及设施状态），不依赖调用方传入的结论，保证三处一致。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.store import store

MODULE = "safety2"

STATION_FIELD = "桩号位置"
TYPE_FIELD = "设施类型"
SPEC_FIELD = "设施规格"
SET_DATE_FIELD = "设置日期"
STATUS_FIELD = "设施状态"

# 台账内部流转状态与展示状态里出现这些字样，都视为设施已拆除/退出服役
RETIRED_KEYWORDS = ("拆除", "废弃", "废止", "停用")
INTERNAL_STATUS_FIELD = "status"
INTERNAL_RETIRED_STATES: tuple[str, ...] = ("已更换",)


@dataclass(frozen=True)
class ServiceStatus:
    """交安设施可养护判断结论。

    serviceable 为最终结论：True 表示设施在役、可以派养护任务；
    False 表示不在役，reason 给出三处共用的拒因文案。
    """

    station: str
    serviceable: bool
    in_service: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        """挂到台账行或详情上的结论字段；可养护时原因为空串。"""
        return {
            "在役": self.in_service,
            "可养护": self.serviceable,
            "判断依据": self.reason,
            STATION_FIELD: self.station,
        }


def find_facility_by_station(station: str | None) -> dict[str, Any] | None:
    """按桩号位置在交安设施台账里定位设施；桩号为空或查不到返回 None。"""
    key = str(station or "").strip()
    if not key:
        return None
    for row in store.rows(MODULE):
        if str(row.get(STATION_FIELD) or "").strip() == key:
            return row
    return None


def _is_retired(row: dict[str, Any]) -> bool:
    shown = str(row.get(STATUS_FIELD) or "")
    if any(word in shown for word in RETIRED_KEYWORDS):
        return True
    internal = str(row.get(INTERNAL_STATUS_FIELD) or "")
    return internal in INTERNAL_RETIRED_STATES


def _parse_set_date(raw: Any) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def judge_by_station(station: str | None, *, today: date | None = None) -> ServiceStatus:
    """按桩号位置取交安设施，依据设施类型、设施规格、设置日期统一给结论。

    顺序即口径：桩号缺失 → 查不到设施 → 已拆除等退出服役状态 →
    类型/规格缺失 → 设置日期缺失、不可解析或晚于今天，任一不满足
    即不在役、不可养护；全部满足才在役可养护。
    """
    key = str(station or "").strip()
    today = today or date.today()

    if not key:
        return ServiceStatus(key, False, False, "桩号位置为空，无法定位交安设施")

    row = find_facility_by_station(key)
    if row is None:
        return ServiceStatus(key, False, False, f"桩号位置「{key}」查无在档交安设施")

    if _is_retired(row):
        return ServiceStatus(key, False, False, f"桩号位置「{key}」的交安设施已拆除，不在役")

    facility_type = str(row.get(TYPE_FIELD) or "").strip()
    if not facility_type:
        return ServiceStatus(key, False, False, f"桩号位置「{key}」的交安设施缺少设施类型，不予养护")

    spec = str(row.get(SPEC_FIELD) or "").strip()
    if not spec:
        return ServiceStatus(key, False, False, f"桩号位置「{key}」的交安设施缺少设施规格，不予养护")

    set_date = _parse_set_date(row.get(SET_DATE_FIELD))
    if set_date is None:
        return ServiceStatus(key, False, False, f"桩号位置「{key}」的交安设施设置日期缺失或无效，不予养护")
    if set_date > today:
        return ServiceStatus(key, False, False, f"桩号位置「{key}」的交安设施设置日期晚于今天，尚未投用")

    return ServiceStatus(key, True, True, "")


def judge_entry(row: dict[str, Any], *, today: date | None = None) -> ServiceStatus:
    """对已取出的交安设施台账行直接给结论（台账与详情使用）。"""
    return judge_by_station(row.get(STATION_FIELD), today=today)


def annotate(row: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
    """把共用结论写回台账行/详情；不改动任何既有字段，仅追加结论字段。"""
    row.update(judge_entry(row, today=today).as_dict())
    return row
