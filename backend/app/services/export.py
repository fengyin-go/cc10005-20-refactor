"""数据分发业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from app.services.base import BaseResourceService

MODULE = "export"
REQUIRED_FIELDS = ["通道编号", "输出数据集", "目标系统"]
STATUS_ORDER = ["草稿", "待校验", "已启用", "已停用"]
ACTION_RULES = {"提交校验": "待校验", "启用通道": "已启用", "停用通道": "已停用"}
NEGATIVE_ACTIONS = ["停用通道"]


class ExportService(BaseResourceService):
    module = MODULE
    entry_label = "分发通道"
    scope_label = "数据分发"
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
