"""流程全景 SVG 数据（对齐 Java ProcessGraphUtil 的输出结构）。

前端 app.js#renderGraphSvg 期望的 graph 结构：
    graph.process: [
        {nodeType, id, name, bounds:{x,y,width,height}, state},      // 形状节点
        {nodeType:"sequenceFlow", id, name, waypoints:[{x,y}], state} // 连线
    ]
    state: "completed" | "active" | "idle"（上色：绿/蓝/灰）

数据来源：部署时保留的原始 BPMN XML 里的 bpmndi:BPMNDiagram（bounds/waypoints
来自 Camunda Modeler 绘图坐标），状态由引擎的活动痕迹 activity_history 推导。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from lxml import etree

_BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
_BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
_DC_NS = "http://www.omg.org/spec/DD/20100524/DC"
_DI_NS = "http://www.omg.org/spec/DD/20100524/DI"
_NS = {
    "bpmn": _BPMN_NS,
    "bpmndi": _BPMNDI_NS,
    "dc": _DC_NS,
    "di": _DI_NS,
}

# 节点类型 -> 前端可识别的小驼峰名（Java activityType 风格）
_TYPE_NAME = {
    "UserTask": "userTask",
    "ServiceTask": "serviceTask",
    "StartEvent": "startEvent",
    "EndEvent": "endEvent",
    "ExclusiveGateway": "exclusiveGateway",
    "ParallelGateway": "parallelGateway",
    "InclusiveGateway": "inclusiveGateway",
    "SubProcess": "subProcess",
    "BoundaryEvent": "boundaryEvent",
    "IntermediateCatchEvent": "intermediateCatchEvent",
    "IntermediateThrowEvent": "intermediateThrowEvent",
    "BusinessRuleTask": "businessRuleTask",
    "ScriptTask": "scriptTask",
    "CallActivity": "callActivity",
}


def node_type_name(cls_name: str) -> str:
    """引擎节点类名 -> 前端 nodeType（UserTask -> userTask）。"""
    if cls_name in _TYPE_NAME:
        return _TYPE_NAME[cls_name]
    return cls_name[:1].lower() + cls_name[1:] if cls_name else ""


def _activity_state(pi, node_id: str) -> str:
    """按活动痕迹推断节点状态：open 未结算 -> active；有结算 -> completed。"""
    last: Optional[Any] = None
    for ai in pi.activity_history:
        if ai.activity_id == node_id:
            last = ai
    if last is None:
        return "idle"
    return "active" if last.end_time is None else "completed"


def build_graph(engine, pi) -> Dict[str, Any]:
    """构建单实例流程图数据（失败返回空 process，不影响全景其余信息）。"""
    key = pi.process_definition_key
    proc = engine.get_process_definition(key)
    xml = engine.get_process_definition_xml(key)
    if not xml:
        return {"process": []}
    try:
        root = etree.fromstring(xml.encode("utf-8"))
    except etree.XMLSyntaxError:
        return {"process": []}

    items: List[Dict[str, Any]] = []

    # ---- 形状节点 ----
    for shape in root.xpath(".//bpmndi:BPMNShape", namespaces=_NS):
        element_id = shape.get("bpmnElement")
        node = proc.flow_nodes.get(element_id) if element_id else None
        if node is None:
            continue
        bounds_el = shape.find("dc:Bounds", _NS)
        if bounds_el is None:
            continue
        items.append(
            {
                "nodeType": node_type_name(type(node).__name__),
                "id": node.id,
                "name": node.name or "",
                "bounds": {
                    "x": float(bounds_el.get("x")),
                    "y": float(bounds_el.get("y")),
                    "width": float(bounds_el.get("width")),
                    "height": float(bounds_el.get("height")),
                },
                "state": _activity_state(pi, node.id),
            }
        )

    # ---- 连线（BPMNEdge waypoints；状态跟随目标节点）----
    for edge in root.xpath(".//bpmndi:BPMNEdge", namespaces=_NS):
        element_id = edge.get("bpmnElement")
        flow = proc.sequence_flows.get(element_id) if element_id else None
        if flow is None:
            continue
        waypoints = [
            {"x": float(w.get("x")), "y": float(w.get("y"))}
            for w in edge.findall("di:waypoint", _NS)
            if w.get("x") is not None
        ]
        if not waypoints:
            continue
        items.append(
            {
                "nodeType": "sequenceFlow",
                "id": flow.id,
                "name": flow.name or "",
                "waypoints": waypoints,
                "state": _activity_state(pi, flow.target_ref),
            }
        )
    return {"process": items}
