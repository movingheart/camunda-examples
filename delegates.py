"""serviceTask 委托实现。

员工申请流程的「执行业务」节点：BPMN 里 ``camunda:class`` 指向
``BusinessExecuteDelegate``（短名），注册名必须一致：

    engine.register_delegate("BusinessExecuteDelegate", business_execute)

请假 -> 登记考勤；硬件申领 -> 生成采购单（示例仅打印日志并写流程变量，
变量可在 Web「流程全景」中查看）。
"""

from __future__ import annotations

import sys
from typing import Any, Dict


def _stdout(text: str) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows GBK
    except Exception:
        pass
    print(text)


def business_execute(variables: Dict[str, Any]) -> Dict[str, Any]:
    """fn(pi.variables) 语义：读变量，返回 dict 会合并进实例变量。"""
    business_key = variables.get("businessKey") or ""
    apply_type = variables.get("applyType") or ""
    reason = variables.get("reason") or ""
    start_by = variables.get("startBy") or ""

    _stdout("==== 执行业务 (serviceTask) ====")
    _stdout(f"业务号: {business_key}")
    _stdout(
        f"申请类型: {apply_type}"
        + (" (请假登记考勤)" if apply_type == "leave" else " (生成采购单/领用登记)")
    )
    _stdout(f"事由: {reason}")
    _stdout(f"发起人: {start_by}")
    _stdout("================================")
    return {
        "businessExecuted": True,
        "businessResult": f"业务执行完成: {business_key}",
    }
