"""Workflow Executor - 本地工作流执行引擎"""

import json
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.workflow_builder import topological_sort


class LocalWorkflowExecutor:
    """本地工作流执行器"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def execute(
        self,
        workflow_id: str,
        nodes: List[dict],
        edges: List[dict],
        inputs: Optional[dict] = None,
        callback=None,
    ) -> Dict[str, Any]:
        from app.models.workflow import WorkflowExecution

        execution = WorkflowExecution(
            id=uuid.uuid4(),
            workflow_id=workflow_id,
            status="running",
            inputs=inputs or {},
            node_results={},
            started_at=datetime.utcnow(),
        )
        self.db.add(execution)
        await self.db.flush()

        if callback:
            await callback("workflow_start", {
                "execution_id": str(execution.id),
                "total_nodes": len(nodes),
            })

        context: Dict[str, Dict] = {}
        node_order = topological_sort(nodes, edges)
        node_map = {n["id"]: n for n in nodes}

        for node_id in node_order:
            node = node_map[node_id]

            if callback:
                await callback("node_start", {
                    "node_id": node_id,
                    "node_name": node.get("name", node_id),
                })

            try:
                params = self._resolve_params(node, context, inputs or {})
                result = await self._execute_node(node, params)

                context[node_id] = {"output": result}
                execution.node_results[node_id] = {
                    "status": "success",
                    "output": _safe_serialize(result),
                }

                if callback:
                    await callback("node_complete", {
                        "node_id": node_id,
                        "status": "success",
                        "output_preview": _safe_serialize(result)[:500] if result else None,
                    })

            except Exception as e:
                logger.error(f"Workflow node {node_id} failed: {e}")
                execution.node_results[node_id] = {
                    "status": "failed",
                    "error": str(e),
                }
                execution.status = "failed"
                execution.failed_node = node_id
                execution.error_message = str(e)

                if callback:
                    await callback("node_complete", {
                        "node_id": node_id,
                        "status": "failed",
                        "error": str(e),
                    })
                break

        execution.finished_at = datetime.utcnow()
        if execution.started_at and execution.finished_at:
            delta = execution.finished_at - execution.started_at
            execution.duration_ms = int(delta.total_seconds() * 1000)

        if execution.status != "failed":
            execution.status = "success"
            execution.outputs = _safe_serialize(self._collect_outputs(nodes, context))

        await self.db.flush()

        if callback:
            final_status = execution.status
            await callback("workflow_complete", {
                "status": final_status,
                "total_duration_ms": execution.duration_ms,
                "error": execution.error_message,
            })

        return {
            "execution_id": str(execution.id),
            "status": execution.status,
            "node_results": execution.node_results,
            "outputs": execution.outputs,
            "duration_ms": execution.duration_ms,
            "error_message": execution.error_message,
            "failed_node": execution.failed_node,
        }

    def _resolve_params(self, node: dict, context: dict, inputs: dict) -> dict:
        params = dict(node.get("config", {}).get("parameters", {}))
        for key, mapping in node.get("config", {}).get("parameter_mappings", {}).items():
            params[key] = self._evaluate_mapping(mapping, context, inputs)
        return params

    def _evaluate_mapping(self, mapping: str, context: dict, inputs: dict) -> Any:
        if not isinstance(mapping, str):
            return mapping
        if mapping.startswith("$upstream."):
            parts = mapping.split(".")
            if len(parts) >= 4:
                node_id = parts[1]
                field = ".".join(parts[3:])
                output = context.get(node_id, {}).get("output", {})
                return _nested_get(output, field)
            elif len(parts) == 3:
                node_id = parts[1]
                return context.get(node_id, {}).get("output")
        elif mapping.startswith("$input."):
            key = mapping.split(".", 1)[1]
            return inputs.get(key)
        return mapping

    async def _execute_node(self, node: dict, params: dict) -> Any:
        node_type = node.get("type", "skill")
        skill_id = node.get("skill_id", "")

        if skill_id == "__builtin_data_reader":
            return await self._execute_reader(params)
        elif skill_id == "__builtin_data_writer":
            return await self._execute_writer(params)
        elif node_type == "skill" and skill_id:
            return await self._execute_skill(skill_id, params)
        else:
            raise ValueError(f"未知节点类型: {node_type}, skill_id: {skill_id}")

    async def _execute_reader(self, params: dict) -> dict:
        from app.services.connectors import ConnectorManager

        datasource_id = params.get("datasource_id") or params.get("datasource")
        table_name = params.get("table_name") or params.get("tables")

        if isinstance(table_name, list):
            table_name = table_name[0] if table_name else ""

        if not datasource_id:
            raise ValueError("数据读取节点缺少 datasource 参数")

        if not table_name:
            raise ValueError("数据读取节点缺少 tables 参数")

        manager = ConnectorManager(self.db)
        table_data = await manager.read_table(datasource_id, table_name)

        rows = table_data.get("rows", []) if isinstance(table_data, dict) else []
        columns = table_data.get("columns", []) if isinstance(table_data, dict) else []

        return {
            "datasource_id": datasource_id,
            "table_names": [table_name],
            "row_count": len(rows),
            "columns": columns,
            "data": rows,
        }

    async def _execute_writer(self, params: dict) -> dict:
        from app.services.connectors import ConnectorManager

        datasource_id = params.get("datasource_id") or params.get("datasource")
        table_name = params.get("table_name") or params.get("tables")
        data = params.get("data") or params.get("records")

        if isinstance(table_name, list):
            table_name = table_name[0] if table_name else ""

        if not datasource_id or not table_name:
            return {"success": True, "rows_written": 0, "skipped": True}

        rows = data if isinstance(data, list) else []
        if rows:
            manager = ConnectorManager(self.db)
            await manager.write_table(datasource_id, table_name, rows)

        return {
            "success": True,
            "datasource_id": datasource_id,
            "table_name": table_name,
            "rows_written": len(rows),
        }

    async def _execute_skill(self, skill_id: str, params: dict) -> Any:
        from app.services.skill_runner import run_skill_script
        from app.models.skill import Skill
        from sqlalchemy import select
        from uuid import UUID as UUIDType
        from pathlib import Path

        try:
            skill_uuid = UUIDType(skill_id) if isinstance(skill_id, str) else skill_id
        except (ValueError, AttributeError):
            skill_uuid = skill_id

        result = await self.db.execute(select(Skill).where(Skill.id == skill_uuid))
        skill = result.scalar_one_or_none()
        if not skill:
            raise ValueError(f"技能不存在: {skill_id}")

        folder = Path(skill.skill_path) if skill.skill_path else None
        if not folder or not folder.exists():
            from app.api.v1.endpoints.skill import _get_skill_folder
            folder = _get_skill_folder(skill_uuid)

        datasource_id = params.pop("datasource_id", params.pop("datasource", None))
        table_name = params.pop("table_name", params.pop("tables", None))

        if isinstance(table_name, list):
            table_name = table_name[0] if table_name else ""

        run_result = run_skill_script(
            skill_path=folder,
            datasource_id=datasource_id,
            table_name=table_name,
            parameters=params,
        )

        if not run_result.get("success"):
            raise RuntimeError(run_result.get("error", "技能执行失败"))

        return run_result.get("result")

    def _collect_outputs(self, nodes: List[dict], context: dict) -> dict:
        outputs = {}
        sink_nodes = []
        node_ids = {n["id"] for n in nodes}
        targets = {e["target"] for e in []}

        for node in nodes:
            is_sink = True
            for n2 in nodes:
                for edge_node in nodes:
                    pass
            outputs[node["id"]] = context.get(node["id"], {}).get("output")

        last_node = nodes[-1] if nodes else None
        if last_node:
            outputs["result"] = context.get(last_node["id"], {}).get("output")

        return outputs


def _nested_get(obj: Any, path: str) -> Any:
    parts = path.split(".")
    current = obj
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, (list, tuple)):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if current is None:
            return None
    return current


def _safe_serialize(obj: Any) -> Any:
    import math
    if obj is None:
        return None
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {str(k): _safe_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_serialize(v) for v in obj]
    if isinstance(obj, (str, int, bool)):
        return obj
    try:
        return str(obj)
    except Exception:
        return None
