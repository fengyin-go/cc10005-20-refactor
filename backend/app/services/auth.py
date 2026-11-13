"""登录凭证业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from app.services.base import BaseResourceService

MODULE = "auth"
REQUIRED_FIELDS = ["凭证编号", "目标站点", "认证方式"]
STATUS_ORDER = ["草稿", "待绑定", "已生效", "已失效"]
ACTION_RULES = {"提交绑定": "待绑定", "启用凭证": "已生效", "标记失效": "已失效"}
NEGATIVE_ACTIONS = []


class AuthService(BaseResourceService):
    module = MODULE
    entry_label = "凭证配置"
    scope_label = "登录凭证"
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
