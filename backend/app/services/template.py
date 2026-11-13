"""抽取模板业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from app.services.base import BaseResourceService

MODULE = "template"
REQUIRED_FIELDS = ["模板编号", "入口地址", "列表选择器"]
STATUS_ORDER = ["草稿", "待校验", "已启用", "已废弃"]
ACTION_RULES = {"提交校验": "待校验", "启用模板": "已启用", "废弃模板": "已废弃"}
NEGATIVE_ACTIONS = []


class TemplateService(BaseResourceService):
    module = MODULE
    entry_label = "网页模板"
    scope_label = "抽取模板"
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
