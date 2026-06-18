"""Workflow Builder - Skill转工作流 + DAG校验"""

import ast
import uuid
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


def validate_dag(nodes: List[dict], edges: List[dict]) -> Tuple[bool, List[str], List[str]]:
    errors = []
    warnings = []

    if not nodes:
        errors.append("工作流没有节点")
        return False, errors, warnings

    node_ids = {n["id"] for n in nodes}

    for edge in edges:
        if edge["source"] not in node_ids:
            errors.append(f"边 {edge['id']} 的源节点 {edge['source']} 不存在")
        if edge["target"] not in node_ids:
            errors.append(f"边 {edge['id']} 的目标节点 {edge['target']} 不存在")

    in_degree = {n["id"]: 0 for n in nodes}
    adjacency = {n["id"]: [] for n in nodes}
    for edge in edges:
        if edge["source"] in node_ids and edge["target"] in node_ids:
            adjacency[edge["source"]].append(edge["target"])
            in_degree[edge["target"]] += 1

    queue = [nid for nid, deg in in_degree.items() if deg == 0]
    visited = []
    while queue:
        node_id = queue.pop(0)
        visited.append(node_id)
        for next_id in adjacency[node_id]:
            in_degree[next_id] -= 1
            if in_degree[next_id] == 0:
                queue.append(next_id)

    if len(visited) != len(nodes):
        errors.append("工作流存在循环依赖")
        return False, errors, warnings

    for node in nodes:
        if node.get("type") == "skill" and not node.get("skill_id"):
            errors.append(f"节点 {node['id']}({node.get('name', '')}) 类型为 skill 但未指定 skill_id")

    roots = [n for n in nodes if in_degree.get(n["id"], 0) == 0]
    if len(roots) > 1:
        warnings.append(f"有 {len(roots)} 个起始节点，它们将并行执行")

    return len(errors) == 0, errors, warnings


def skill_to_workflow(
    skill_id: str,
    skill_name: str,
    skill_display_name: Optional[str],
    skill_description: Optional[str],
    script_content: str,
    skill_params: List[dict],
) -> Dict[str, Any]:
    """将 Skill 转换为工作流定义"""
    nodes = []
    edges = []

    has_read = _detect_data_read(script_content)
    has_write = _detect_data_write(script_content)

    x_pos = 50
    node_counter = 0

    if has_read:
        nodes.append({
            "id": "node_read",
            "type": "skill",
            "skill_id": "__builtin_data_reader",
            "name": "数据读取",
            "config": {
                "parameters": {},
                "parameter_mappings": {
                    "datasource": "$input.datasource",
                    "tables": "$input.tables",
                },
            },
            "position": {"x": x_pos, "y": 200},
            "retry": 1,
            "timeout": 120,
        })
        x_pos += 300
        node_counter += 1

    core_node = {
        "id": "node_core",
        "type": "skill",
        "skill_id": str(skill_id),
        "name": skill_display_name or skill_name,
        "config": {"parameters": {}, "parameter_mappings": {}},
        "position": {"x": x_pos, "y": 200},
        "retry": 0,
        "timeout": 300,
    }

    for p in skill_params:
        if not p.get("is_datasource") and not p.get("is_table"):
            if p.get("default") is not None:
                core_node["config"]["parameters"][p["name"]] = p["default"]

    nodes.append(core_node)
    core_idx = node_counter
    node_counter += 1
    x_pos += 300

    if has_read:
        core_node["config"]["parameter_mappings"] = {
            "datasource": "$upstream.node_read.output.datasource_id",
            "tables": "$upstream.node_read.output.table_names",
        }
        edges.append({
            "id": "e_read_core",
            "source": "node_read",
            "target": "node_core",
        })

    if has_write:
        write_node = {
            "id": "node_write",
            "type": "skill",
            "skill_id": "__builtin_data_writer",
            "name": "数据写入",
            "config": {
                "parameters": {},
                "parameter_mappings": {
                    "data": "$upstream.node_core.output.result",
                },
            },
            "position": {"x": x_pos, "y": 200},
            "retry": 1,
            "timeout": 120,
        }
        if has_read:
            write_node["config"]["parameter_mappings"]["datasource"] = "$upstream.node_read.output.datasource_id"
            write_node["config"]["parameter_mappings"]["tables"] = "$upstream.node_read.output.table_names"

        nodes.append(write_node)
        edges.append({
            "id": "e_core_write",
            "source": "node_core",
            "target": "node_write",
        })

    workflow_params = {}
    for p in skill_params:
        if p.get("is_datasource") or p.get("is_table"):
            workflow_params[p["name"]] = {
                "type": p.get("type", "str"),
                "required": p.get("required", False),
                "description": p.get("description", ""),
            }

    return {
        "name": f"wf_{skill_name}",
        "display_name": f"{skill_display_name or skill_name} - 工作流",
        "description": skill_description or f"从技能 {skill_name} 转换的工作流",
        "engine": "local",
        "nodes": nodes,
        "edges": edges,
        "parameters": workflow_params,
        "source_skill_id": skill_id,
    }


def _detect_data_read(script: str) -> bool:
    markers = ["query_table_data", "get_table_data", "read_table", "load_table"]
    for m in markers:
        if m in script:
            return True
    return False


def _detect_data_write(script: str) -> bool:
    markers = ["write_table_data", "write_table_data_back", "save_table", "write_back"]
    for m in markers:
        if m in script:
            return True
    return False


def topological_sort(nodes: List[dict], edges: List[dict]) -> List[str]:
    in_degree = {n["id"]: 0 for n in nodes}
    adjacency = {n["id"]: [] for n in nodes}
    node_ids = {n["id"] for n in nodes}
    for edge in edges:
        if edge["source"] in node_ids and edge["target"] in node_ids:
            adjacency[edge["source"]].append(edge["target"])
            in_degree[edge["target"]] += 1

    queue = [nid for nid, deg in in_degree.items() if deg == 0]
    result = []
    while queue:
        node_id = queue.pop(0)
        result.append(node_id)
        for next_id in adjacency[node_id]:
            in_degree[next_id] -= 1
            if in_degree[next_id] == 0:
                queue.append(next_id)

    if len(result) != len(nodes):
        raise ValueError("工作流存在循环依赖，无法拓扑排序")

    return result
