"""失败重试业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from app.services.base import BaseResourceService

MODULE = "retry"
REQUIRED_FIELDS = ["策略编号", "关联任务", "最大重试次数"]
STATUS_ORDER = ["草稿", "待校验", "已启用", "已停用"]
ACTION_RULES = {"提交校验": "待校验", "启用策略": "已启用", "停用策略": "已停用"}
NEGATIVE_ACTIONS = ["停用策略"]


class RetryService(BaseResourceService):
    module = MODULE
    entry_label = "重试策略"
    scope_label = "失败重试"
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
