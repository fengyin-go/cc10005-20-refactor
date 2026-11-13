"""内存数据仓库：所有业务模块共享的资源访问边界。

设计目标（资源读写隔离）：

* 读路径只交出**快照副本**：``rows`` / ``find`` / ``snapshot`` 返回深拷贝，调用方
  怎么整理都不会回写到仓库；快照带统一的 ``captured_at`` 读取时间点，供节点可用性
  与请求窗口等跨资源裁决共用同一时点的数据。
* 写路径只经过资源操作：``create`` / ``mutate`` / ``transact``，外部拿不到内部
  可变对象，不存在“改查询结果即改仓库”的旁路。
* 每条记录带可辨认的 ``version``：更新者必须基于快照里的版本写入，版本过期时收到
  :class:`VersionConflict` 冲突回执，避免以旧容量覆盖新额度。
* 每个模块一把独立读写锁：只读访问并行放行，写入独占；互不关联的模块不会被一把
  全局锁串成队列。
* 跨模块变动走 :meth:`Store.transact`：固定顺序加锁、先整体校验再统一变更，任一步
  写入受阻就整体撤销。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from app.seed import SEED_ROWS

# 快照读取时间点的时钟：默认取系统时间，测试里可替换成可控时钟。
Clock = Callable[[], float]


class EntryNotFound(Exception):
    """资源操作指向的记录在仓库中不存在（或已归档）。"""

    def __init__(self, module: str, entry_id: int) -> None:
        self.module = module
        self.entry_id = entry_id
        super().__init__(f"{module} 模块中不存在 id={entry_id} 的记录")


class VersionConflict(Exception):
    """更新者手里的快照版本已过期，仓库记录已被别人推进过。"""

    def __init__(self, module: str, entry_id: int, expected: int, current: int) -> None:
        self.module = module
        self.entry_id = entry_id
        self.expected = expected
        self.current = current
        super().__init__(
            f"{module} 模块 id={entry_id} 版本冲突：期望 {expected}，当前 {current}"
        )


class RWLock:
    """够用的读优先读写锁：读共享、写独占，同模块读多写少。

    刻意不做写者优先，因为本仓库写入频率很低，读并行是主要诉求；写者会在所有在途
    读结束后拿到锁，不会饥饿到不可接受。
    """

    def __init__(self) -> None:
        self._cond = threading.Condition(threading.Lock())
        self._readers = 0
        self._writer = False

    def acquire_read(self) -> None:
        with self._cond:
            while self._writer:
                self._cond.wait()
            self._readers += 1

    def release_read(self) -> None:
        with self._cond:
            self._readers -= 1
            if self._readers == 0:
                self._cond.notify_all()

    def acquire_write(self) -> None:
        with self._cond:
            while self._writer or self._readers:
                self._cond.wait()
            self._writer = True

    def release_write(self) -> None:
        with self._cond:
            self._writer = False
            self._cond.notify_all()

    @contextmanager
    def read_locked(self) -> Iterator[None]:
        self.acquire_read()
        try:
            yield
        finally:
            self.release_read()

    @contextmanager
    def write_locked(self) -> Iterator[None]:
        self.acquire_write()
        try:
            yield
        finally:
            self.release_write()


@dataclass(frozen=True)
class ResourceSnapshot:
    """一次读取得到的资源快照：数据是副本，时间点是明确的。"""

    module: str
    rows: list[dict[str, Any]]
    versions: dict[int, int]
    captured_at: float

    def version_of(self, entry_id: int) -> int | None:
        return self.versions.get(entry_id)


@dataclass(frozen=True)
class CreateOp:
    """在指定模块新增一条记录。"""

    module: str
    row: dict[str, Any]


@dataclass(frozen=True)
class MutateOp:
    """按版本对单条记录做字段级变更；``expected_version`` 为 None 时不做版本校验。"""

    module: str
    entry_id: int
    patch: dict[str, Any]
    expected_version: int | None = None


@dataclass
class _PreparedOp:
    """事务内部的预解析结果，不对外暴露。"""

    op: CreateOp | MutateOp
    target: dict[str, Any] | None = None
    new_id: int | None = None


class Store:
    def __init__(self, clock: Clock | None = None) -> None:
        self._clock: Clock = clock or time.time
        # 锁表本身也要一把看护锁，只在“取/建模块锁”这种极短临界区使用，
        # 不参与业务读写，避免退化成全局排队。
        self._locks_guard = threading.Lock()
        self._locks: dict[str, RWLock] = {}
        self._tables: dict[str, list[dict[str, Any]]] = {}
        # 每条记录的版本号独立存放，不混进行数据，保证对外字段结构与原列表一致。
        self._versions: dict[str, dict[int, int]] = {}
        self.reset()

    # ------------------------------------------------------------------ 内部工具
    def reset(self) -> None:
        """恢复到种子数据状态，主要给测试一个确定的起点。"""
        with self._locks_guard:
            self._tables = {
                name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
            }
            self._versions = {
                name: {int(row["id"]): 1 for row in rows}
                for name, rows in self._tables.items()
            }
            self._locks = {name: RWLock() for name in self._tables}

    def _lock_for(self, module: str) -> RWLock:
        with self._locks_guard:
            lock = self._locks.get(module)
            if lock is None:
                lock = RWLock()
                self._locks[module] = lock
                self._tables.setdefault(module, [])
                self._versions.setdefault(module, {})
            return lock

    @staticmethod
    def _index_of(rows: list[dict[str, Any]], entry_id: int) -> int:
        for index, row in enumerate(rows):
            if int(row.get("id", 0)) == entry_id:
                return index
        return -1

    @staticmethod
    def _coerce_id(raw: Any, rows: list[dict[str, Any]]) -> int:
        """把调用方给的 id 归一为正整数；缺省时在当前表内取自增值。"""
        candidate = int(raw or 0)
        if candidate:
            return candidate
        return max((int(item.get("id", 0)) for item in rows), default=0) + 1

    # ------------------------------------------------------------------ 只读路径
    def module_names(self) -> list[str]:
        # 名字列表也是一份副本，调用方排序/增删不影响仓库。
        with self._locks_guard:
            return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        """返回模块全表的深拷贝；保留原列表顺序，调用方可自由整理。"""
        lock = self._lock_for(module)
        with lock.read_locked():
            return deepcopy(self._tables.setdefault(module, []))

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        """返回单条记录的深拷贝；查不到返回 None。"""
        lock = self._lock_for(module)
        with lock.read_locked():
            for row in self._tables.setdefault(module, []):
                if int(row.get("id", 0)) == entry_id:
                    return deepcopy(row)
        return None

    def version_of(self, module: str, entry_id: int) -> int | None:
        """读取某条记录当前版本；记录不存在时返回 None。"""
        lock = self._lock_for(module)
        with lock.read_locked():
            return self._versions.setdefault(module, {}).get(entry_id)

    def snapshot(self, module: str) -> ResourceSnapshot:
        """给单个模块拍一张带时间点的只读快照。"""
        captured_at = self._clock()
        lock = self._lock_for(module)
        with lock.read_locked():
            table = self._tables.setdefault(module, [])
            return ResourceSnapshot(
                module=module,
                rows=deepcopy(table),
                versions=dict(self._versions.setdefault(module, {})),
                captured_at=captured_at,
            )

    def snapshot_many(self, modules: list[str] | tuple[str, ...]) -> dict[str, ResourceSnapshot]:
        """跨模块拍一组**同一时间点**的快照，供联合裁决使用。

        按模块名排序加锁，所有调用方走同一顺序，杜绝交叉加锁导致的死锁。
        """
        captured_at = self._clock()
        ordered = sorted(set(modules))
        for name in ordered:
            self._lock_for(name).acquire_read()
        try:
            result: dict[str, ResourceSnapshot] = {}
            for name in ordered:
                table = self._tables.setdefault(name, [])
                result[name] = ResourceSnapshot(
                    module=name,
                    rows=deepcopy(table),
                    versions=dict(self._versions.setdefault(name, {})),
                    captured_at=captured_at,
                )
            return result
        finally:
            for name in reversed(ordered):
                self._lock_for(name).release_read()

    def overview(self) -> dict[str, object]:
        names = self.module_names()
        snapshots = self.snapshot_many(names)
        modules: list[dict[str, object]] = []
        for name in names:
            rows = snapshots[name].rows
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}

    # ------------------------------------------------------------------ 写入路径
    def create(self, module: str, row: dict[str, Any]) -> dict[str, Any]:
        """新增一条记录并赋予初始版本 1；返回写入后的副本。"""
        lock = self._lock_for(module)
        with lock.write_locked():
            rows = self._tables.setdefault(module, [])
            entry_id = self._coerce_id(row.get("id"), rows)
            if self._index_of(rows, entry_id) >= 0:
                raise ValueError(f"{module} 模块 id={entry_id} 已存在，不能重复登记")
            stored = deepcopy(row)
            stored["id"] = entry_id
            rows.append(stored)
            self._versions.setdefault(module, {})[entry_id] = 1
            return deepcopy(stored)

    def mutate(
        self,
        module: str,
        entry_id: int,
        patch: dict[str, Any],
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """按版本对单条记录打补丁，成功后版本号 +1 并返回新副本。

        ``expected_version`` 不为 None 且与当前版本不一致时抛 :class:`VersionConflict`，
        仓库内容保持不变。
        """
        lock = self._lock_for(module)
        with lock.write_locked():
            rows = self._tables.setdefault(module, [])
            index = self._index_of(rows, entry_id)
            if index < 0:
                raise EntryNotFound(module, entry_id)
            current_version = self._versions.setdefault(module, {}).get(entry_id, 1)
            if expected_version is not None and expected_version != current_version:
                raise VersionConflict(module, entry_id, expected_version, current_version)
            rows[index].update(deepcopy(patch))
            self._versions[module][entry_id] = current_version + 1
            return deepcopy(rows[index])

    def transact(self, operations: list[CreateOp | MutateOp]) -> dict[str, dict[str, Any]]:
        """跨模块原子提交一批资源操作。

        固定顺序加锁 → 全量预校验（存在性、版本、id 冲突）→ 统一变更。任何一步
        校验失败或变更中抛错，都按变更前深拷贝整体回滚，对外呈现“要么全成要么全不动”。
        返回值按模块归类写入后的记录副本。
        """
        ordered_modules = sorted({op.module for op in operations})
        for name in ordered_modules:
            self._lock_for(name).acquire_write()
        try:
            # 变更前留底，异常路径靠它撤销。
            backup = {
                name: (
                    deepcopy(self._tables.setdefault(name, [])),
                    dict(self._versions.setdefault(name, {})),
                )
                for name in ordered_modules
            }
            try:
                prepared = self._prepare_transaction(operations)
                return self._commit_transaction(prepared)
            except Exception:
                for name, (rows, versions) in backup.items():
                    self._tables[name] = rows
                    self._versions[name] = versions
                raise
        finally:
            for name in reversed(ordered_modules):
                self._lock_for(name).release_write()

    def _prepare_transaction(
        self, operations: list[CreateOp | MutateOp]
    ) -> list[_PreparedOp]:
        """第一阶段：解析所有操作并完成全部校验，此阶段不改任何数据。"""
        prepared: list[_PreparedOp] = []
        # 已存在记录在 prepare 阶段尚未落盘，每次都对照快照原始版本校验；
        # local_versions 只跟踪本事务内“先建后改”的新记录版本。
        local_versions: dict[tuple[str, int], int] = {}
        # 本次事务将要新增的行（commit 前不入主表），供后续操作定位新记录。
        created_rows: dict[tuple[str, int], dict[str, Any]] = {}

        for op in operations:
            rows = self._tables.setdefault(op.module, [])
            version_table = self._versions.setdefault(op.module, {})

            if isinstance(op, CreateOp):
                new_id = self._coerce_id(op.row.get("id"), rows)
                if self._index_of(rows, new_id) >= 0 or (op.module, new_id) in created_rows:
                    raise ValueError(f"{op.module} 模块 id={new_id} 已存在，不能重复登记")
                stored = deepcopy(op.row)
                stored["id"] = new_id
                created_rows[(op.module, new_id)] = stored
                local_versions[(op.module, new_id)] = 1
                prepared.append(_PreparedOp(op=op, target=stored, new_id=new_id))
                continue

            index = self._index_of(rows, op.entry_id)
            if index >= 0:
                target = rows[index]
                current_version = version_table.get(op.entry_id, 1)
            elif (op.module, op.entry_id) in created_rows:
                target = created_rows[(op.module, op.entry_id)]
                current_version = local_versions[(op.module, op.entry_id)]
            else:
                raise EntryNotFound(op.module, op.entry_id)

            if op.expected_version is not None and op.expected_version != current_version:
                raise VersionConflict(
                    op.module, op.entry_id, op.expected_version, current_version
                )
            prepared.append(_PreparedOp(op=op, target=target))
            # 仅新记录的本地版本会在后续“先建后改”分支被读取。
            local_versions[(op.module, op.entry_id)] = current_version + 1
        return prepared

    def _commit_transaction(
        self, prepared: list[_PreparedOp]
    ) -> dict[str, dict[str, Any]]:
        """第二阶段：校验已全部通过，按顺序落地变更并收集结果。"""
        result: dict[str, dict[str, Any]] = {}
        for item in prepared:
            op = item.op
            if isinstance(op, CreateOp):
                assert item.new_id is not None and item.target is not None
                rows = self._tables.setdefault(op.module, [])
                rows.append(item.target)
                self._versions.setdefault(op.module, {})[item.new_id] = 1
                result[op.module] = deepcopy(item.target)
            else:
                assert item.target is not None
                version_table = self._versions.setdefault(op.module, {})
                current_version = version_table.get(op.entry_id, 1)
                item.target.update(deepcopy(op.patch))
                version_table[op.entry_id] = current_version + 1
                result[op.module] = deepcopy(item.target)
        return result


store = Store()
