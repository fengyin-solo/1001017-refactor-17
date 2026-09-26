"""交安设施在役/可养护统一口径的回归测试。

重点保证：
1. 台账列表、设施详情、派养护任务登记校验三处结论同源且一致；
2. 判断只读不写，台账原始数据（含历史养护记录、现有展示字段）不被改动。
"""
from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import safety2_policy  # noqa: E402
from app.services.safety2 import Safety2Service  # noqa: E402
from app.store import store  # noqa: E402

TODAY = date(2026, 9, 26)


def make_facility(
    stake: str,
    *,
    ftype: str | None = "标志牌",
    spec: str | None = "单柱式 600×600",
    install: str | None = "2026-01-01",
) -> dict:
    return {
        "id": 900,
        "status": "完好",
        "pending": True,
        "abnormal": False,
        "设施编号": "SAFE-TEST",
        "设施类型": ftype,
        "所在路段": "测试路",
        "桩号位置": stake,
        "设施规格": spec,
        "设置日期": install,
        "养护记录": "历史养护记录-保持原样",
        "设施状态": "完好",
    }


class Safety2PolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = store.rows(safety2_policy.MODULE)
        self.snapshot = [dict(row) for row in self.rows]
        self.service = Safety2Service()

    def tearDown(self) -> None:
        self.rows.clear()
        self.rows.extend(self.snapshot)

    def install(self, row: dict) -> dict:
        row["id"] = max((int(r.get("id", 0)) for r in self.rows), default=0) + 1
        self.rows.append(row)
        return row

    def test_normal_facility_maintainable_at_all_three_points(self) -> None:
        row = self.install(make_facility("K1+000"))

        verdict = safety2_policy.evaluate_by_stake("K1+000", today=TODAY)
        self.assertTrue(verdict.maintainable)
        self.assertTrue(verdict.found)

        items, _ = self.service.list_entries(page=1, size=200)
        listed = next(item for item in items if item["id"] == row["id"])
        detail = self.service.get_entry(row["id"])
        self.assertIsNotNone(detail)

        self.assertEqual(listed[safety2_policy.MAINTAINABLE_FIELD], True)
        self.assertEqual(detail[safety2_policy.MAINTAINABLE_FIELD], True)

        updated, message = self.service.run_action(row["id"], "安排维修")
        self.assertIsNotNone(updated)
        self.assertIn("安排维修", message)
        self.assertEqual(updated["status"], "维修中")

    def test_missing_spec_blocks_maintenance_everywhere(self) -> None:
        row = self.install(make_facility("K1+100", spec="  "))

        items, _ = self.service.list_entries(page=1, size=200)
        listed = next(item for item in items if item["id"] == row["id"])
        detail = self.service.get_entry(row["id"])
        verdict = safety2_policy.evaluate_by_stake("K1+100", today=TODAY)

        self.assertFalse(verdict.maintainable)
        self.assertIn("设施规格", verdict.reason)
        self.assertEqual(listed[safety2_policy.MAINTAINABLE_FIELD], False)
        self.assertEqual(detail[safety2_policy.MAINTAINABLE_FIELD], False)
        self.assertEqual(listed[safety2_policy.VERDICT_REASON_FIELD], verdict.reason)
        self.assertEqual(detail[safety2_policy.VERDICT_REASON_FIELD], verdict.reason)

        # 养护记录登记校验：不允许派养护任务，状态保持原样
        updated, message = self.service.run_action(row["id"], "安排维修")
        self.assertIsNone(updated)
        self.assertIn("不能派养护任务", message)
        self.assertEqual(store.find(safety2_policy.MODULE, row["id"])["status"], "完好")

        # 登记损坏不是派养护任务，不受在役口径拦截
        damaged, _ = self.service.run_action(row["id"], "登记损坏")
        self.assertIsNotNone(damaged)

    def test_future_install_date_means_not_in_service(self) -> None:
        future = (TODAY + timedelta(days=1)).isoformat()
        row = self.install(make_facility("K1+200", install=future))
        verdict = safety2_policy.evaluate_facility(row, today=TODAY)
        self.assertFalse(verdict.maintainable)
        self.assertIn("尚未设置", verdict.reason)

    def test_invalid_date_is_rejected(self) -> None:
        row = self.install(make_facility("K1+300", install="2026/01/01"))
        verdict = safety2_policy.evaluate_facility(row, today=TODAY)
        self.assertFalse(verdict.maintainable)
        self.assertIn("不是合法日期", verdict.reason)

    def test_missing_type_and_missing_install_date(self) -> None:
        self.assertFalse(
            safety2_policy.evaluate_facility(
                make_facility("K1+400", ftype=None), today=TODAY
            ).maintainable
        )
        self.assertFalse(
            safety2_policy.evaluate_by_stake("K1+500", today=TODAY).maintainable
        )
        self.assertFalse(
            safety2_policy.evaluate_by_stake("", today=TODAY).maintainable
        )

    def test_verdict_does_not_mutate_ledger_rows_or_history(self) -> None:
        row = self.install(make_facility("K1+600"))
        original = dict(row)

        self.service.list_entries(page=1, size=200)
        self.service.get_entry(row["id"])
        safety2_policy.evaluate_by_stake("K1+600", today=TODAY)

        stored = store.find(safety2_policy.MODULE, row["id"])
        self.assertEqual(stored, original)
        self.assertNotIn(safety2_policy.MAINTAINABLE_FIELD, stored)
        self.assertNotIn(safety2_policy.VERDICT_REASON_FIELD, stored)
        self.assertEqual(stored["养护记录"], "历史养护记录-保持原样")

    def test_existing_display_fields_keep_shape(self) -> None:
        row = self.install(make_facility("K1+700"))
        columns = [
            "设施编号", "设施类型", "所在路段", "桩号位置",
            "设施规格", "设置日期", "养护记录", "设施状态",
        ]
        items, _ = self.service.list_entries(page=1, size=200)
        listed = next(item for item in items if item["id"] == row["id"])
        for column in columns:
            self.assertEqual(listed[column], row[column])


if __name__ == "__main__":
    unittest.main()
