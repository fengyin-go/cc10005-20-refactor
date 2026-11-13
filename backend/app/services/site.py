"""站点管理业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from app.services.base import BaseResourceService

MODULE = "site"
REQUIRED_FIELDS = ["站点编号", "域名地址", "站点类型"]
STATUS_ORDER = ["草稿", "待校验", "已激活", "已暂停"]
ACTION_RULES = {"提交校验": "待校验", "激活站点": "已激活", "暂停站点": "已暂停"}
NEGATIVE_ACTIONS = []


class SiteService(BaseResourceService):
    module = MODULE
    entry_label = "采集站点"
    scope_label = "站点管理"
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
