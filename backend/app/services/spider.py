"""采集任务业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from app.services.base import BaseResourceService

MODULE = "spider"
REQUIRED_FIELDS = ["作业编号", "目标站点", "抽取模板"]
STATUS_ORDER = ["草稿", "待执行", "运行中", "已完成", "已失败"]
ACTION_RULES = {"提交执行": "待执行", "启动采集": "运行中", "终止采集": "已失败", "归档结果": "已完成"}
NEGATIVE_ACTIONS = []


class SpiderService(BaseResourceService):
    module = MODULE
    entry_label = "采集作业"
    scope_label = "采集任务"
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
