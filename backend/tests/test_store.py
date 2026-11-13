"""仓库层测试：快照隔离、乐观版本、事务原子性与模块级读写锁。

只依赖标准库，直接在内存仓库上验证，不需要启动 HTTP 服务。
"""
from __future__ import annotations

import threading
import time
import unittest
from copy import deepcopy

from app.store import (
    CreateOp,
    EntryNotFound,
    MutateOp,
    Store,
    VersionConflict,
)


class StoreIsolationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = Store()
        self.store.reset()

    def test_rows_returns_deep_copy(self) -> None:
        rows = self.store.rows("proxy")
        original = deepcopy(rows)
        rows[0]["status"] = "已移除"
        rows.append({"id": 999})
        # 再次读取必须反映仓库原值，调用方的整理不回流。
        self.assertEqual(self.store.rows("proxy"), original)
        self.assertEqual(len(self.store.rows("proxy")), 3)

    def test_find_returns_deep_copy(self) -> None:
        entry = self.store.find("proxy", 1)
        assert entry is not None
        entry["节点编号"] = "TAMPERED"
        again = self.store.find("proxy", 1)
        assert again is not None
        self.assertEqual(again["节点编号"], "PROX-0001")

    def test_list_order_preserved(self) -> None:
        ids = [row["id"] for row in self.store.rows("proxy")]
        self.assertEqual(ids, [1, 2, 3])

    def test_snapshot_carries_versions_and_timestamp(self) -> None:
        snapshot = self.store.snapshot("proxy")
        self.assertEqual(snapshot.module, "proxy")
        self.assertIsInstance(snapshot.captured_at, float)
        self.assertEqual(snapshot.versions, {1: 1, 2: 1, 3: 1})
        # 快照副本同样隔离。
        snapshot.rows[0]["status"] = "已移除"
        self.assertEqual(self.store.find("proxy", 1)["status"], "草稿")

    def test_snapshot_many_shares_single_timestamp(self) -> None:
        snaps = self.store.snapshot_many(["ratelimit", "proxy"])
        stamps = {s.captured_at for s in snaps.values()}
        self.assertEqual(len(stamps), 1)
        self.assertEqual(set(snaps), {"proxy", "ratelimit"})


class StoreVersionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = Store()
        self.store.reset()

    def test_mutate_requires_matching_version(self) -> None:
        entry = self.store.mutate("proxy", 1, {"status": "可用"}, expected_version=1)
        self.assertEqual(entry["status"], "可用")
        self.assertEqual(self.store.version_of("proxy", 1), 2)
        # 旧版本再次写入必须被拒绝，且仓库内容不变。
        with self.assertRaises(VersionConflict) as ctx:
            self.store.mutate("proxy", 1, {"status": "已移除"}, expected_version=1)
        self.assertEqual(ctx.exception.current, 2)
        self.assertEqual(self.store.find("proxy", 1)["status"], "可用")

    def test_mutate_without_version_skips_check(self) -> None:
        self.store.mutate("proxy", 1, {"status": "可用"})
        self.assertEqual(self.store.version_of("proxy", 1), 2)

    def test_mutate_missing_entry_raises(self) -> None:
        with self.assertRaises(EntryNotFound):
            self.store.mutate("proxy", 404, {"status": "可用"}, expected_version=1)

    def test_create_assigns_incremental_id_and_version(self) -> None:
        stored = self.store.create("proxy", {"节点编号": "PROX-NEW"})
        self.assertEqual(stored["id"], 4)
        self.assertEqual(self.store.version_of("proxy", 4), 1)
        with self.assertRaises(ValueError):
            self.store.create("proxy", {"id": 1, "节点编号": "DUP"})

    def test_patch_is_copied_not_referenced(self) -> None:
        patch = {"代理地址": "addr-1"}
        self.store.mutate("proxy", 1, patch, expected_version=1)
        patch["代理地址"] = "tampered"
        self.assertEqual(self.store.find("proxy", 1)["代理地址"], "addr-1")


class StoreTransactionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = Store()
        self.store.reset()

    def test_cross_module_commit_applies_both(self) -> None:
        result = self.store.transact([
            MutateOp("proxy", 1, {"status": "可用"}, expected_version=1),
            MutateOp("ratelimit", 1, {"每秒请求上限": 88}, expected_version=1),
        ])
        self.assertEqual(set(result), {"proxy", "ratelimit"})
        self.assertEqual(self.store.find("proxy", 1)["status"], "可用")
        self.assertEqual(self.store.find("ratelimit", 1)["每秒请求上限"], 88)
        self.assertEqual(self.store.version_of("proxy", 1), 2)
        self.assertEqual(self.store.version_of("ratelimit", 1), 2)

    def test_stale_version_rolls_back_everything(self) -> None:
        before_proxy = deepcopy(self.store.find("proxy", 2))
        before_rate = deepcopy(self.store.find("ratelimit", 2))
        with self.assertRaises(VersionConflict):
            self.store.transact([
                MutateOp("proxy", 2, {"status": "已移除"}, expected_version=99),
                MutateOp("ratelimit", 2, {"每秒请求上限": 1}, expected_version=1),
            ])
        self.assertEqual(self.store.find("proxy", 2), before_proxy)
        self.assertEqual(self.store.find("ratelimit", 2), before_rate)
        self.assertEqual(self.store.version_of("proxy", 2), 1)
        self.assertEqual(self.store.version_of("ratelimit", 2), 1)

    def test_missing_entry_rolls_back_everything(self) -> None:
        before = deepcopy(self.store.find("ratelimit", 3))
        with self.assertRaises(EntryNotFound):
            self.store.transact([
                MutateOp("proxy", 3, {"status": "可用"}, expected_version=1),
                MutateOp("ratelimit", 999, {"每秒请求上限": 1}, expected_version=1),
            ])
        self.assertEqual(self.store.find("ratelimit", 3), before)
        self.assertEqual(self.store.find("proxy", 3)["status"], "不可用")

    def test_duplicate_create_rolls_back(self) -> None:
        with self.assertRaises(ValueError):
            self.store.transact([
                CreateOp("proxy", {"id": 1, "节点编号": "DUP"}),
                MutateOp("ratelimit", 1, {"每秒请求上限": 5}, expected_version=1),
            ])
        # 第二步也必须撤销。
        self.assertEqual(self.store.find("ratelimit", 1)["每秒请求上限"], "限速控制样例1")

    def test_create_then_mutate_within_one_transaction(self) -> None:
        result = self.store.transact([
            CreateOp("proxy", {"节点编号": "PROX-NEW", "status": "草稿"}),
        ])
        new_id = int(result["proxy"]["id"])
        self.store.transact([
            MutateOp("proxy", new_id, {"status": "可用"}, expected_version=1),
        ])
        self.assertEqual(self.store.find("proxy", new_id)["status"], "可用")
        self.assertEqual(self.store.version_of("proxy", new_id), 2)

    def test_create_then_mutate_new_row_in_single_transaction(self) -> None:
        # 同一事务内先建后改：新记录在 commit 前不入主表，靠 created_rows 定位。
        result = self.store.transact([
            CreateOp("proxy", {"节点编号": "PROX-TX", "status": "草稿",
                               "pending": True, "abnormal": False}),
            MutateOp("proxy", 4, {"status": "可用"}, expected_version=1),
        ])
        # 两个操作命中同一模块同一记录，结果归并为一条。
        self.assertEqual(result["proxy"]["status"], "可用")
        stored = self.store.find("proxy", 4)
        self.assertEqual(stored["节点编号"], "PROX-TX")
        self.assertEqual(stored["status"], "可用")
        self.assertEqual(self.store.version_of("proxy", 4), 2)

    def test_two_mutates_same_existing_entry_against_snapshot_version(self) -> None:
        # 同一事务内对已存在记录的两次变更，都对照快照原始版本 1 校验。
        self.store.transact([
            MutateOp("proxy", 1, {"status": "可用"}, expected_version=1),
            MutateOp("proxy", 1, {"pending": False}, expected_version=1),
        ])
        entry = self.store.find("proxy", 1)
        self.assertEqual(entry["status"], "可用")
        self.assertFalse(entry["pending"])
        # 两次变更各推进一个版本，版本号从 1 走到 3；回滚仍由整事务兜底。
        self.assertEqual(self.store.version_of("proxy", 1), 3)

    def test_empty_transaction_is_noop(self) -> None:
        self.assertEqual(self.store.transact([]), {})


class StoreConcurrencyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = Store()
        self.store.reset()

    def test_reads_of_unrelated_modules_run_in_parallel(self) -> None:
        # 写锁占住 proxy，ratelimit 的只读必须立刻通过，证明没有全局排队。
        entered = threading.Event()
        release = threading.Event()

        def hold_proxy_write() -> None:
            with self.store._lock_for("proxy").write_locked():
                entered.set()
                release.wait(3)

        writer = threading.Thread(target=hold_proxy_write)
        writer.start()
        self.assertTrue(entered.wait(2))
        start = time.perf_counter()
        self.store.rows("ratelimit")
        self.assertLess(time.perf_counter() - start, 0.2)
        release.set()
        writer.join(2)

    def test_same_module_read_waits_for_write(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        done = threading.Event()

        def hold_write() -> None:
            with self.store._lock_for("proxy").write_locked():
                entered.set()
                release.wait(3)

        def do_read() -> None:
            self.store.rows("proxy")
            done.set()

        writer = threading.Thread(target=hold_write)
        reader = threading.Thread(target=do_read)
        writer.start()
        self.assertTrue(entered.wait(2))
        reader.start()
        self.assertFalse(done.wait(0.3))
        release.set()
        self.assertTrue(done.wait(2))
        writer.join(2)
        reader.join(2)

    def test_concurrent_mutates_serialize_and_keep_versions_consistent(self) -> None:
        errors: list[Exception] = []

        def bump(times: int) -> None:
            for _ in range(times):
                try:
                    current = self.store.version_of("proxy", 1)
                    self.store.mutate("proxy", 1, {"pending": True}, current)
                except VersionConflict:
                    # 并发下乐观锁冲突是预期行为，重试一次即可。
                    current = self.store.version_of("proxy", 1)
                    self.store.mutate("proxy", 1, {"pending": True}, current)
                except Exception as exc:  # pragma: no cover - 防御性
                    errors.append(exc)

        threads = [threading.Thread(target=bump, args=(20,)) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
        self.assertEqual(errors, [])
        self.assertEqual(self.store.version_of("proxy", 1), 81)


if __name__ == "__main__":
    unittest.main()
