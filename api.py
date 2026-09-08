"""FastAPI 业务路由。

响应契约统一为 ``{success, data | message}``：
    GET  /api/users            用户列表
    POST /api/start            发起请假 (leave)
    POST /api/start/employee   发起员工申请 (proc_employee_apply)
    POST /api/start/expense    发起报销 (expense)
    GET  /api/todos            我的待办（userId + mstrleId 双通道）
    POST /api/approve          办理任务（通过/驳回/驳回重提）
    GET  /api/mine             我发起的
    GET  /api/process/detail   流程全景（变量/轨迹/日志/流程图）
    GET  /api/logs             操作日志

任务归属在应用层判定（camunda-python 不解析 ``camunda:assignee /
candidateUsers`` 表达式属性）：

- **任务归属**：按「流程 key + 任务节点 id」静态映射（= BPMN 表达式意图），
  ``by_start_by`` -> 发起人本人；``role`` -> 查 ``mst_flw_rle`` 规则展开。
- **审批例外**：审批类任务不允许发起人本人办理。
- **操作日志**：``start`` / ``approve`` 成功后写 ``mst_flw_fsvlog``。
"""

from __future__ import annotations

import functools
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Body, FastAPI, Query
from fastapi.staticfiles import StaticFiles

from biz import Biz
from graph import build_graph, node_type_name

from camunda.engine.process_engine import ProcessEngine

WEBAPP_DIR = Path(__file__).resolve().parent / "webapp"

USERS: List[Dict[str, str]] = [
    {"id": "u001", "name": "张三", "dpt": "研发部", "title": "后端开发工程师", "role": "manager_role"},
    {"id": "u002", "name": "李四", "dpt": "研发部", "title": "测试工程师", "role": "manager_role"},
    {"id": "u003", "name": "王五", "dpt": "研发部", "title": "项目经理", "role": "manager_role"},
    {"id": "u004", "name": "赵六", "dpt": "市场部", "title": "市场专员", "role": "employee_role"},
    {"id": "u005", "name": "孙七", "dpt": "市场部", "title": "市场总监", "role": "boss_role"},
]

# 任务归属：值 = (归属方式, 规则变量名)。by_start_by 对应 BPMN assignee=${startBy}；
# role 对应 candidateUsers=${xxx_users} + candidateGroups=${xxx_groups}（规则表并集）。
_TASK_OWNER: Dict[Tuple[str, str], Tuple[str, Optional[str]]] = {
    ("leave", "submitTask"): ("by_start_by", None),
    ("leave", "approveTask"): ("role", "manager"),
    ("expense", "submitTask"): ("by_start_by", None),
    ("expense", "managerTask"): ("role", "manager"),
    ("expense", "financeTask"): ("role", "finance"),
    ("proc_employee_apply", "task_leader_approve"): ("role", "leader"),
    ("proc_employee_apply", "task_employee_modify"): ("by_start_by", None),
    ("proc_employee_apply", "task_manager_approve"): ("role", "manager"),
}

# 「提交」类任务（写日志的 opr_typ=Submit，办理人=发起人）
_SUBMIT_KEYS = {
    ("leave", "submitTask"),
    ("expense", "submitTask"),
    ("proc_employee_apply", "task_employee_modify"),
}

# 待办卡片回显的业务变量
_ECHO_KEYS = ("reason", "days", "applyType", "detail", "needManager", "amount")
# 流程变量里不面向业务展示的引擎注入键
_SYS_KEYS = {"businessKey", "startBy"}


def _wrap(fn):
    """业务异常一律 {success:false, message}，HTTP 200。"""

    @functools.wraps(fn)
    def inner(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "message": str(exc)}

    return inner


def _to_view(ts: Optional[str]) -> str:
    """ISO 时间 -> 'yyyy-MM-dd HH:mm:ss'（前端 fmtTime 兼容）。"""
    return (ts or "").replace("T", " ")[:19]


def _business_key(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000)}"


def create_app(engine: ProcessEngine, biz: Biz) -> FastAPI:
    app = FastAPI(
        title="flowengine 流程示例 (camunda-python)",
        docs_url=None,
        redoc_url=None,
    )

    # ---------------- 内部辅助 ----------------
    def _def_name(key: str) -> str:
        try:
            return engine.get_process_definition(key).name or key
        except Exception:
            return key

    def _running_by_bk(business_key: str) -> Optional[Any]:
        """业务号 -> 最新运行中实例（同一业务号不允许并发活动流程）。"""
        cands = [
            pi for pi in engine.list_process_instances()
            if pi.business_key == business_key and not pi.is_completed
        ]
        if not cands:
            return None
        cands.sort(key=lambda p: p.start_time or "")
        return cands[-1]

    def _echo(pi) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k in _ECHO_KEYS:
            if k in pi.variables:
                out[k] = pi.variables[k]
        return out

    def _owner(pi, task) -> Tuple[str, Optional[str]]:
        return _TASK_OWNER.get(
            (pi.process_definition_key, task.task_definition_key), ("none", None)
        )

    def _can_do(pi, task, user_id: str, mstrle_id: str) -> bool:
        """待办/办理权限（= assignee / candidate 求值 + 审批例外）。"""
        task_name = task.name or ""
        start_by = pi.variables.get("startBy") or ""
        if task_name.endswith("审批") and start_by == user_id:
            return False  # 审批节点不允许发起人自己办理
        kind, var = _owner(pi, task)
        if kind == "by_start_by":
            return start_by == user_id
        if kind == "role" and var:
            users, roles = biz.users_for_role(var)
            return user_id in users or (bool(mstrle_id) and mstrle_id in roles)
        return False

    def _node_type(pi, activity_id: str) -> str:
        try:
            node = engine.get_process_definition(pi.process_definition_key).flow_nodes.get(activity_id)
            return node_type_name(type(node).__name__) if node is not None else ""
        except Exception:
            return ""

    def _assignee_of(pi, activity_id: str) -> Optional[str]:
        """该活动最近一次完成的办理人（completed_tasks 关联）。"""
        matched = [
            t for t in pi.completed_tasks if t.task_definition_key == activity_id
        ]
        if not matched:
            return None
        matched.sort(key=lambda t: t.end_time or t.create_time or "")
        return matched[-1].assignee

    # ---------------- 用户 / 发起 ----------------
    @app.get("/api/users")
    def users():
        return {"success": True, "data": USERS}

    @app.post("/api/start")
    @_wrap
    def start_leave(body: Dict[str, Any] = Body(...)):
        user_id = str(body.get("userId", ""))
        reason = str(body.get("reason", ""))
        days = int(body.get("days", 1))
        bk = _business_key("LV")
        if _running_by_bk(bk):
            raise ValueError(f"流程发起失败: 同一业务ID流程尚未结束: {bk}")
        engine.start_process_instance_by_key(
            "leave",
            {"reason": reason, "days": days, "businessKey": bk, "startBy": user_id},
            business_key=bk,
        )
        biz.write_log(flw_kid="leave", bus_kid=bk, opr=user_id, tsk_nme="",
                      opr_typ="Start", opr_ret="true",
                      opr_ifo=f"请假申请已提交, 请假 {days} 天")
        return {"success": True, "businessKey": bk,
                "message": f"请假申请已提交, 业务号: {bk}"}

    @app.post("/api/start/employee")
    @_wrap
    def start_employee(body: Dict[str, Any] = Body(...)):
        user_id = str(body.get("userId", ""))
        apply_type = str(body.get("applyType", "leave"))
        reason = str(body.get("reason", ""))
        detail = str(body.get("detail", ""))
        need_manager = bool(body.get("needManager", False))
        bk = _business_key("EA")
        if _running_by_bk(bk):
            raise ValueError(f"流程发起失败: 同一业务ID流程尚未结束: {bk}")
        engine.start_process_instance_by_key(
            "proc_employee_apply",
            {"applyType": apply_type, "reason": reason, "detail": detail,
             "needManager": need_manager, "businessKey": bk, "startBy": user_id},
            business_key=bk,
        )
        type_txt = "请假" if apply_type == "leave" else "硬件申领"
        biz.write_log(flw_kid="proc_employee_apply", bus_kid=bk, opr=user_id,
                      tsk_nme="", opr_typ="Start", opr_ret="true",
                      opr_ifo=f"{type_txt}申请已提交: {reason}")
        return {"success": True, "businessKey": bk,
                "message": f"{type_txt}申请已提交, 业务号: {bk}"}

    @app.post("/api/start/expense")
    @_wrap
    def start_expense(body: Dict[str, Any] = Body(...)):
        user_id = str(body.get("userId", ""))
        amount = float(body.get("amount", 0))
        reason = str(body.get("reason", ""))
        detail = str(body.get("detail", ""))
        bk = _business_key("EX")
        if _running_by_bk(bk):
            raise ValueError(f"流程发起失败: 同一业务ID流程尚未结束: {bk}")
        engine.start_process_instance_by_key(
            "expense",
            {"amount": amount, "reason": reason, "detail": detail,
             "businessKey": bk, "startBy": user_id},
            business_key=bk,
        )
        biz.write_log(flw_kid="expense", bus_kid=bk, opr=user_id, tsk_nme="",
                      opr_typ="Start", opr_ret="true",
                      opr_ifo=f"报销申请已提交, 金额 {amount:g} 元")
        return {"success": True, "businessKey": bk,
                "message": f"报销申请已提交, 业务号: {bk}"}

    # ---------------- 待办 / 办理 ----------------
    @app.get("/api/todos")
    def todos(
        userId: str = Query(""),
        mstrleId: str = Query(""),
    ):
        data: List[Dict[str, Any]] = []
        for pi in engine.list_process_instances():
            if pi.is_completed:
                continue
            for t in engine.create_task_query(process_instance_id=pi.id):
                if not _can_do(pi, t, userId, mstrleId):
                    continue
                task_name = t.name or ""
                data.append({
                    "businessKey": pi.business_key,
                    "processDefinitionKey": pi.process_definition_key,
                    "processDefinitionName": _def_name(pi.process_definition_key),
                    "processStartTime": _to_view(pi.start_time),
                    "taskName": task_name,
                    "taskCreateTime": _to_view(t.create_time),
                    "isModifyTask": "修改" in task_name,
                    "variables": _echo(pi),
                })
        data.sort(key=lambda it: it["taskCreateTime"] or "", reverse=True)
        return {"success": True, "data": data}

    @app.post("/api/approve")
    @_wrap
    def approve(body: Dict[str, Any] = Body(...)):
        user_id = str(body.get("userId", ""))
        mstrle_id = str(body.get("mstrleId", ""))
        business_key = str(body.get("businessKey", ""))
        task_name = str(body.get("taskName", ""))
        approved = bool(body.get("approved", False))
        comment = str(body.get("comment", ""))
        # 驳回重提：申请表单字段已在 body.variables 回填（更新流程变量）
        variables = dict(body.get("variables") or {})

        pi = _running_by_bk(business_key)
        if pi is None:
            raise ValueError(f"操作失败: 流程不存在或已结束: {business_key}")
        tasks = [
            t for t in engine.create_task_query(process_instance_id=pi.id)
            if (t.name or "") == task_name
        ]
        if not tasks:
            raise ValueError(f"操作失败: 任务不存在或无权操作: {task_name}")
        task = tasks[0]
        if not _can_do(pi, task, user_id, mstrle_id):
            raise ValueError(f"操作失败: 任务不存在或无权操作: {task_name}")

        is_modify = "修改" in task_name
        # 修改重提：完成时 approved 置 true 重新进入审批流（对齐 BPMN taskListener）
        variables["approved"] = True if is_modify else approved

        engine.set_assignee(task.id, user_id)      # 办理人落任务历史（轨迹显示）
        engine.complete_task(task.id, variables)

        ret = "true" if (approved or is_modify) else "false"
        typ = "Submit" if (pi.process_definition_key, task.task_definition_key) in _SUBMIT_KEYS else "Approve"
        msg = comment or ("已通过" if ret == "true" else "已驳回")
        if is_modify:
            msg = comment or "修改后重新提交"
        biz.write_log(flw_kid=pi.process_definition_key, bus_kid=business_key,
                      opr=user_id, tsk_nme=task_name, opr_typ=typ, opr_ret=ret,
                      opr_ifo=msg)
        return {"success": True,
                "message": f"流程任务处理完成: {task_name} -> {msg}"}

    # ---------------- 我发起的 / 全景 / 日志 ----------------
    @app.get("/api/mine")
    def mine(userId: str = Query("")):
        data: List[Dict[str, Any]] = []
        for pi in engine.list_process_instances():
            if (pi.variables.get("startBy") or "") != userId:
                continue
            data.append({
                "businessKey": pi.business_key,
                "processDefinitionName": _def_name(pi.process_definition_key),
                "state": "已结束" if pi.is_completed else "进行中",
                "startTime": _to_view(pi.start_time),
                "endTime": _to_view(pi.end_time),
            })
        data.sort(key=lambda it: it["startTime"] or "", reverse=True)
        return {"success": True, "data": data}

    @app.get("/api/process/detail")
    def process_detail(businessKey: str = Query("")):
        cands = [
            pi for pi in engine.list_process_instances()
            if pi.business_key == businessKey
        ]
        if not cands:
            raise ValueError(f"未找到流程, 业务号: {businessKey}")
        cands.sort(key=lambda p: p.start_time or "")
        pi = cands[-1]

        variables = {k: v for k, v in pi.variables.items() if k not in _SYS_KEYS}
        current_tasks = [
            {"taskName": t.name or "", "taskCreateTime": _to_view(t.create_time)}
            for t in engine.create_task_query(process_instance_id=pi.id)
            if t.end_time is None
        ]
        activities = []
        for ai in pi.activity_history:
            assignee = _assignee_of(pi, ai.activity_id)
            activities.append({
                "activityId": ai.activity_id,
                "activityName": ai.activity_name,
                "nodeType": _node_type(pi, ai.activity_id),
                "state": "active" if ai.end_time is None else "completed",
                "assignee": assignee,
                "startTime": _to_view(ai.start_time),
                "endTime": _to_view(ai.end_time),
            })
        data = {
            "businessKey": pi.business_key,
            "processDefinitionKey": pi.process_definition_key,
            "processDefinitionName": _def_name(pi.process_definition_key),
            "startUserId": pi.variables.get("startBy") or "",
            "state": "已结束" if pi.is_completed else "进行中",
            "startTime": _to_view(pi.start_time),
            "endTime": _to_view(pi.end_time),
            "currentTasks": current_tasks,
            "variables": variables,
            "activities": activities,
            "logs": biz.fetch_logs(bus_kid=businessKey, limit=None, order="asc"),
            "graph": build_graph(engine, pi),
        }
        return {"success": True, "data": data}

    @app.get("/api/logs")
    def logs():
        return {"success": True, "data": biz.fetch_logs(order="desc")}

    # 静态前端（最后注册，/api/* 路由优先）
    app.mount("/", StaticFiles(directory=str(WEBAPP_DIR), html=True), name="web")
    return app
