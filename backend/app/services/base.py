"""业务服务基类：把各模块共同的快照读取与资源操作收敛到一条链路上。

子类只需要声明模块名、中文字段、状态序列与动作规则；所有写入都经过
:mod:`app.store` 的资源操作，服务层不再持有仓库内部对象的引用。
"""
from __future__ import annotations

from typing import Any, ClassVar

from app.store import EntryNotFound, VersionConflict, store


class BaseResourceService:
    # 子类必须覆盖的类属性 --------------------------------------------------
    module: ClassVar[str] = ""
    entry_label: ClassVar[str] = ""          # 中文记录名，如“代理节点”
    scope_label: ClassVar[str] = ""          # 中文模块名，如“代理池管理”
    required_fields: ClassVar[list[str]] = []
    status_order: ClassVar[list[str]] = []
    action_rules: ClassVar[dict[str, str]] = {}
    negative_actions: ClassVar[list[str]] = []
    # 开启后对外记录会带 version 字段，供乐观锁裁决；默认关闭以维持其余模块原结构。
    expose_version: ClassVar[bool] = False

    def _with_version(self, entry: dict[str, Any] | None) -> dict[str, Any] | None:
        if entry is None or not self.expose_version:
            return entry
        version = store.version_of(self.module, int(entry["id"]))
        enriched = dict(entry)
        enriched["version"] = version
        return enriched

    # ------------------------------------------------------------------ 只读
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        # 快照副本：过滤、分页、调用方再怎么改都不会回流到仓库。
        snapshot = store.snapshot(self.module)
        rows = snapshot.rows
        keyword_field = self.required_fields[0] if self.required_fields else ""
        if keyword:
            rows = [row for row in rows if keyword in str(row.get(keyword_field, ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if self.expose_version:
            rows = [
                {**row, "version": snapshot.versions.get(int(row["id"]), 1)}
                for row in rows
            ]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return self._with_version(store.find(self.module, entry_id))

    # ------------------------------------------------------------------ 写入
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [
            field for field in self.required_fields
            if not str(values.get(field) or "").strip()
        ]
        if missing:
            return None, missing
        entry: dict[str, Any] = {}
        entry.update({field: values.get(field) for field in self.required_fields})
        entry["status"] = self.status_order[0]
        entry["pending"] = True
        entry["abnormal"] = False
        # 唯一写入口：仓库在写锁内原子分配 id 并赋予初始版本。
        stored = store.create(self.module, entry)
        return self._with_version(stored), []

    def update_entry(
        self,
        entry_id: int,
        values: dict[str, Any],
        expected_version: int | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """按快照版本编辑业务字段；保留 id/status 等系统字段不被外部覆盖。"""
        patch = {
            key: value
            for key, value in values.items()
            if key not in ("id", "status", "pending", "abnormal", "version")
        }
        if not patch:
            return None, "没有可更新的字段，请至少提交一个业务字段"
        try:
            entry = store.mutate(self.module, entry_id, patch, expected_version)
        except EntryNotFound:
            return None, f"{self.entry_label} {entry_id} 不存在或已归档"
        except VersionConflict as conflict:
            return None, self._conflict_message(entry_id, conflict)
        return self._with_version(entry), f"{self.entry_label}已更新"

    def run_action(
        self,
        entry_id: int,
        action: str,
        expected_version: int | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        if action not in self.action_rules:
            return None, f"动作「{action}」不属于{self.scope_label}可执行范围"
        target = self.action_rules[action]
        if target not in self.status_order:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        patch = {
            "status": target,
            "pending": target != self.status_order[-1],
            "abnormal": action in self.negative_actions,
        }
        try:
            entry = store.mutate(self.module, entry_id, patch, expected_version)
        except EntryNotFound:
            return None, f"{self.entry_label} {entry_id} 不存在或已归档"
        except VersionConflict as conflict:
            return None, self._conflict_message(entry_id, conflict)
        return self._with_version(entry), f"{self.entry_label}已{action}"

    def _conflict_message(self, entry_id: int, conflict: VersionConflict) -> str:
        return (
            f"{self.entry_label} {entry_id} 的资源版本已过期"
            f"（提交版本 {conflict.expected}，当前版本 {conflict.current}），请刷新快照后重试"
        )
