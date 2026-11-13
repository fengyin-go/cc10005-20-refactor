"""业务服务测试：快照读取隔离、动作语义、版本冲突回执与中文字段口径。"""
from __future__ import annotations

import unittest

from app.services.proxy import ProxyService
from app.services.ratelimit import RatelimitService
from app.services.site import SiteService
from app.store import store


class ServiceSnapshotTest(unittest.TestCase):
    def setUp(self) -> None:
        store.reset()
        self.proxy = ProxyService()
        self.rate = RatelimitService()

    def test_list_returns_independent_copies(self) -> None:
        items, total = self.proxy.list_entries()
        self.assertEqual(total, 3)
        items[0]["status"] = "已移除"
        again, _ = self.proxy.list_entries()
        self.assertEqual(again[0]["status"], "草稿")

    def test_filter_and_pagination_keep_order(self) -> None:
        items, total = self.proxy.list_entries(status="草稿", page=1, size=10)
        self.assertEqual(total, 1)
        self.assertEqual(items[0]["节点编号"], "PROX-0001")
        page_one, _ = self.proxy.list_entries(page=1, size=2)
        page_two, _ = self.proxy.list_entries(page=2, size=2)
        self.assertEqual([r["id"] for r in page_one], [1, 2])
        self.assertEqual([r["id"] for r in page_two], [3])

    def test_exposed_version_on_target_modules(self) -> None:
        items, _ = self.proxy.list_entries()
        self.assertTrue(all("version" in row for row in items))
        detail = self.proxy.get_entry(1)
        self.assertEqual(detail["version"], 1)
        # 非重点模块保持原字段结构，不额外透出 version。
        site_items, _ = SiteService().list_entries()
        self.assertNotIn("version", site_items[0])

    def test_keyword_filter_uses_chinese_field(self) -> None:
        items, total = self.proxy.list_entries(keyword="PROX-0002")
        self.assertEqual(total, 1)
        self.assertEqual(items[0]["id"], 2)


class ServiceActionTest(unittest.TestCase):
    def setUp(self) -> None:
        store.reset()
        self.proxy = ProxyService()
        self.rate = RatelimitService()

    def test_action_transitions_status_and_flags(self) -> None:
        entry, message = self.proxy.run_action(1, "标记可用", expected_version=1)
        self.assertEqual(entry["status"], "可用")
        self.assertTrue(entry["pending"])
        self.assertFalse(entry["abnormal"])
        self.assertEqual(message, "代理节点已标记可用")
        self.assertEqual(entry["version"], 2)

    def test_negative_action_marks_abnormal(self) -> None:
        entry, _ = self.rate.run_action(2, "停用限速", expected_version=1)
        self.assertEqual(entry["status"], "已停用")
        self.assertTrue(entry["abnormal"])
        self.assertFalse(entry["pending"])

    def test_unknown_action_rejected(self) -> None:
        entry, message = self.proxy.run_action(1, "格式化硬盘")
        self.assertIsNone(entry)
        self.assertIn("不属于代理池管理可执行范围", message)

    def test_missing_entry_message(self) -> None:
        entry, message = self.proxy.run_action(404, "标记可用", expected_version=1)
        self.assertIsNone(entry)
        self.assertEqual(message, "代理节点 404 不存在或已归档")

    def test_stale_snapshot_gets_conflict_receipt(self) -> None:
        self.proxy.run_action(1, "标记可用", expected_version=1)
        entry, message = self.proxy.run_action(1, "移除节点", expected_version=1)
        self.assertIsNone(entry)
        self.assertIn("资源版本已过期", message)
        self.assertIn("提交版本 1", message)
        self.assertIn("当前版本 2", message)
        # 冲突写入不落地。
        self.assertEqual(store.find("proxy", 1)["status"], "可用")

    def test_legacy_call_without_version_still_works(self) -> None:
        entry, _ = self.proxy.run_action(1, "标记可用")
        self.assertEqual(entry["status"], "可用")


class ServiceCreateUpdateTest(unittest.TestCase):
    def setUp(self) -> None:
        store.reset()
        self.proxy = ProxyService()
        self.rate = RatelimitService()

    def test_create_requires_chinese_fields(self) -> None:
        entry, missing = self.proxy.create_entry({"节点编号": "P"})
        self.assertIsNone(entry)
        self.assertEqual(missing, ["代理地址", "代理协议"])

    def test_create_assigns_id_and_initial_version(self) -> None:
        entry, missing = self.proxy.create_entry({
            "节点编号": "PROX-0100",
            "代理地址": "10.0.0.1",
            "代理协议": "http",
        })
        self.assertEqual(missing, [])
        self.assertEqual(entry["id"], 4)
        self.assertEqual(entry["version"], 1)
        self.assertEqual(entry["status"], "草稿")

    def test_update_business_field_with_version(self) -> None:
        entry, message = self.rate.update_entry(
            1, {"每秒请求上限": 120, "令牌桶容量": 300}, expected_version=1
        )
        self.assertEqual(entry["每秒请求上限"], 120)
        self.assertEqual(entry["version"], 2)
        self.assertEqual(message, "限速配置已更新")

    def test_update_rejects_reserved_fields(self) -> None:
        entry, message = self.rate.update_entry(1, {"status": "已停用"}, expected_version=1)
        self.assertIsNone(entry)
        self.assertIn("没有可更新的字段", message)
        self.assertEqual(store.find("ratelimit", 1)["status"], "草稿")

    def test_update_stale_version_keeps_old_quota(self) -> None:
        # 先把额度改到新值。
        self.rate.update_entry(1, {"每秒请求上限": 200}, expected_version=1)
        # 拿着旧快照的更新者试图用旧容量覆盖。
        entry, message = self.rate.update_entry(
            1, {"每秒请求上限": 50}, expected_version=1
        )
        self.assertIsNone(entry)
        self.assertIn("资源版本已过期", message)
        self.assertEqual(store.find("ratelimit", 1)["每秒请求上限"], 200)


if __name__ == "__main__":
    unittest.main()
