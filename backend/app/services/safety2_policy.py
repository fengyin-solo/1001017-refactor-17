"""交安设施「是否在役、可否养护」判断的唯一口径。

交安设施台账、设施详情、养护记录登记三处需要同一份结论时，
一律调用本模块的 evaluate_by_stake / evaluate_facility，
不得在各自代码里再抄一遍判断；以后调整口径只改这一处。

口径：按桩号位置从交安设施台账取到该设施，设施类型、设施规格
与设置日期三项齐备，且设置日期不晚于当天（设施确已设置）的，
才判定为在役、可安排养护任务；任一条件不满足即不可养护，
并在 reason 里给出可读原因。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.store import store

MODULE = "safety2"
STAKE_FIELD = "桩号位置"
TYPE_FIELD = "设施类型"
SPEC_FIELD = "设施规格"
INSTALL_DATE_FIELD = "设置日期"

# 台账/详情输出结论时挂在记录上的字段名，三处保持一致
MAINTAINABLE_FIELD = "可养护"
VERDICT_REASON_FIELD = "在役判断"


@dataclass(frozen=True)
class MaintainabilityVerdict:
    """按统一口径给出的交安设施可养护结论。"""

    stake: str
    found: bool
    maintainable: bool
    reason: str
    facility_type: str | None = None
    facility_spec: str | None = None
    install_date: str | None = None

    def attach(self, row: dict[str, Any]) -> dict[str, Any]:
        """把结论合并进记录副本，不改台账原始数据，也不改变既有展示字段。"""
        enriched = dict(row)
        enriched[MAINTAINABLE_FIELD] = self.maintainable
        enriched[VERDICT_REASON_FIELD] = self.reason
        return enriched


def _text(row: dict[str, Any], field: str) -> str:
    return str(row.get(field) or "").strip()


def find_facility_by_stake(stake: str) -> dict[str, Any] | None:
    """按桩号位置在交安设施台账中定位设施；桩号为空或查无记录时返回 None。"""
    stake = str(stake or "").strip()
    if not stake:
        return None
    for row in store.rows(MODULE):
        if _text(row, STAKE_FIELD) == stake:
            return row
    return None


def evaluate_facility(
    row: dict[str, Any] | None,
    *,
    stake: str | None = None,
    today: date | None = None,
) -> MaintainabilityVerdict:
    """对已取到的设施记录给结论；row 为 None 视为该桩号查无登记。

    设施类型、设施规格与设置日期都从记录里现取，台账、详情与养护
    登记传入的记录走完全相同的判断顺序。
    """
    today = today or date.today()
    stake_value = str(stake or (row.get(STAKE_FIELD) if row else "") or "").strip()

    if row is None:
        return MaintainabilityVerdict(
            stake=stake_value,
            found=False,
            maintainable=False,
            reason=f"桩号位置「{stake_value}」在交安设施台账中查无登记，设施不在役，不可养护",
        )

    facility_type = _text(row, TYPE_FIELD)
    facility_spec = _text(row, SPEC_FIELD)
    install_date_text = _text(row, INSTALL_DATE_FIELD)

    if not facility_type:
        reason = f"桩号位置「{stake_value}」的设施类型缺失，无法确认在役交安设施，不可养护"
    elif not facility_spec:
        reason = f"桩号位置「{stake_value}」的设施规格缺失，无法确认在役交安设施，不可养护"
    elif not install_date_text:
        reason = f"桩号位置「{stake_value}」的设置日期缺失，无法确认设施已设置，不可养护"
    else:
        try:
            install_date = date.fromisoformat(install_date_text)
        except ValueError:
            install_date = None
            reason = (
                f"桩号位置「{stake_value}」的设置日期「{install_date_text}」"
                "不是合法日期（应为 YYYY-MM-DD），无法确认在役，不可养护"
            )
        else:
            if install_date > today:
                reason = (
                    f"桩号位置「{stake_value}」的设置日期「{install_date_text}」"
                    f"晚于今日（{today.isoformat()}），设施尚未设置，不在役，不可养护"
                )
            else:
                reason = "设施在役，可安排养护任务"

    maintainable = reason == "设施在役，可安排养护任务"
    return MaintainabilityVerdict(
        stake=stake_value,
        found=True,
        maintainable=maintainable,
        reason=reason,
        facility_type=facility_type or None,
        facility_spec=facility_spec or None,
        install_date=install_date_text or None,
    )


def evaluate_by_stake(stake: str, *, today: date | None = None) -> MaintainabilityVerdict:
    """养护登记入口：只给桩号位置，由本函数负责取设施并给统一结论。"""
    stake_value = str(stake or "").strip()
    if not stake_value:
        return MaintainabilityVerdict(
            stake="",
            found=False,
            maintainable=False,
            reason="未提供桩号位置，无法核对交安设施是否在役，不可养护",
        )
    return evaluate_facility(find_facility_by_stake(stake_value), stake=stake_value, today=today)
