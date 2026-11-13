"""增量采集业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from app.services.base import BaseResourceService

MODULE = "delta"
REQUIRED_FIELDS = ["游标编号", "目标站点", "增量字段"]
STATUS_ORDER = ["草稿", "待校验", "运行中", "已暂停"]
ACTION_RULES = {"提交校验": "待校验", "启动增量": "运行中", "暂停增量": "已暂停"}
NEGATIVE_ACTIONS = []


class DeltaService(BaseResourceService):
    module = MODULE
    entry_label = "增量游标"
    scope_label = "增量采集"
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
