"""资源协调服务测试：联合快照时间点与跨资源整体确认/撤销。"""
from __future__ import annotations

import unittest

from app.services.resource import resource_coordinator
from app.store import store


class CoordinatorSnapshotTest(unittest.TestCase):
    def setUp(self) -> None:
        store.reset()

    def test_joint_snapshot_uses_one_timestamp(self) -> None:
        payload = resource_coordinator.read_snapshot()
        self.assertIn("captured_at", payload)
        resources = payload["resources"]
        self.assertEqual(set(resources), {"proxy", "ratelimit"})
        stamps = {item["captured_at"] for item in resources.values()}
        self.assertEqual(len(stamps), 1)
        self.assertEqual(payload["captured_at"], stamps.pop())
        # 快照带每记录版本。
        self.assertEqual(resources["proxy"]["versions"], {1: 1, 2: 1, 3: 1})

    def test_snapshot_is_a_copy(self) -> None:
        payload = resource_coordinator.read_snapshot()
        payload["resources"]["proxy"]["rows"][0]["status"] = "已移除"
        self.assertEqual(store.find("proxy", 1)["status"], "草稿")


class CoordinatorAdjustmentTest(unittest.TestCase):
    def setUp(self) -> None:
        store.reset()

    def test_cross_resource_adjustment_commits_atomically(self) -> None:
        result, message = resource_coordinator.apply_adjustment([
            {"module": "proxy", "entry_id": 2, "version": 1, "action": "标记不可用"},
            {"module": "ratelimit", "entry_id": 2, "version": 1,
             "fields": {"每秒请求上限": 60, "令牌桶容量": 90}},
        ])
        self.assertIsNotNone(result)
        self.assertEqual(message, "资源调整已整体确认")
        self.assertEqual(result["count"], 2)
        self.assertEqual(store.find("proxy", 2)["status"], "不可用")
        self.assertEqual(store.find("ratelimit", 2)["每秒请求上限"], 60)
        self.assertEqual(store.version_of("proxy", 2), 2)
        self.assertEqual(store.version_of("ratelimit", 2), 2)

    def test_any_stale_version_rolls_back_whole_adjustment(self) -> None:
        before_proxy = store.find("proxy", 3)
        before_rate = store.find("ratelimit", 3)
        result, message = resource_coordinator.apply_adjustment([
            {"module": "proxy", "entry_id": 3, "version": 99, "action": "移除节点"},
            {"module": "ratelimit", "entry_id": 3, "version": 1,
             "fields": {"每秒请求上限": 5}},
        ])
        self.assertIsNone(result)
        self.assertIn("版本冲突", message)
        self.assertIn("整体撤销", message)
        self.assertEqual(store.find("proxy", 3), before_proxy)
        self.assertEqual(store.find("ratelimit", 3), before_rate)

    def test_missing_entry_rolls_back(self) -> None:
        result, message = resource_coordinator.apply_adjustment([
            {"module": "proxy", "entry_id": 1, "version": 1, "action": "标记可用"},
            {"module": "ratelimit", "entry_id": 999, "version": 1,
             "fields": {"每秒请求上限": 5}},
        ])
        self.assertIsNone(result)
        self.assertIn("不存在或已归档", message)
        self.assertEqual(store.find("proxy", 1)["status"], "草稿")

    def test_invalid_module_rejected_before_write(self) -> None:
        result, message = resource_coordinator.apply_adjustment([
            {"module": "spider", "entry_id": 1, "version": 1, "fields": {"x": 1}},
        ])
        self.assertIsNone(result)
        self.assertIn("不受资源协调服务管辖", message)

    def test_unknown_action_rejected_before_write(self) -> None:
        result, message = resource_coordinator.apply_adjustment([
            {"module": "proxy", "entry_id": 1, "version": 1, "action": "关机"},
        ])
        self.assertIsNone(result)
        self.assertIn("不属于该资源可执行范围", message)

    def test_empty_adjustment(self) -> None:
        result, message = resource_coordinator.apply_adjustment([])
        self.assertIsNone(result)
        self.assertIn("为空", message)

    def test_reserved_fields_cannot_be_overwritten_via_coordinator(self) -> None:
        result, message = resource_coordinator.apply_adjustment([
            {"module": "ratelimit", "entry_id": 1, "version": 1,
             "fields": {"id": 999, "status": "已停用", "每秒请求上限": 33}},
        ])
        self.assertIsNotNone(result)
        entry = store.find("ratelimit", 1)
        self.assertEqual(entry["id"], 1)
        self.assertEqual(entry["status"], "草稿")
        self.assertEqual(entry["每秒请求上限"], 33)


class RouterAssemblyTest(unittest.TestCase):
    def test_routes_registered(self) -> None:
        from app.main import app

        paths = set(app.openapi()["paths"])
        self.assertIn("/api/resources/snapshot", paths)
        self.assertIn("/api/resources/adjustments", paths)
        self.assertIn("/api/proxy/{entry_id}", paths)
        self.assertIn("/api/ratelimit/{entry_id}", paths)

    def test_export_route_registered_before_param_route(self) -> None:
        # /export 必须先于 /{entry_id} 注册，否则会被整数参数拦截成 422。
        from app.routers.proxy import router as proxy_router
        from app.routers.ratelimit import router as rate_router

        for router, prefix in ((proxy_router, "/api/proxy"), (rate_router, "/api/ratelimit")):
            ordered = [getattr(route, "path", "") for route in router.routes]
            self.assertIn(f"{prefix}/export", ordered)
            self.assertLess(
                ordered.index(f"{prefix}/export"),
                ordered.index(f"{prefix}/{{entry_id}}"),
            )


if __name__ == "__main__":
    unittest.main()
