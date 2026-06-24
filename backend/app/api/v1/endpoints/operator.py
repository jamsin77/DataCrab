"""算子管理API端点"""

import io
import time
import traceback
import sys
import json
import asyncio
import inspect
import threading
from uuid import UUID
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from loguru import logger

from app.core.database import get_db, async_session
from app.models.operator import Operator
from app.models.user import User
from app.schemas.operator import (
    OperatorCreate,
    OperatorUpdate,
    OperatorResponse,
    OperatorScriptUpdate,
    OperatorDebugRequest,
    OperatorDebugResponse,
    OperatorGenerateRequest,
    OperatorModifyRequest,
    OperatorCloneRequest,
)
from app.services.operator_parser import parse_python_script, extract_script_name
from app.services.agent import agent_service, AgentContext
from app.services.llm import llm_manager
from app.api.deps import get_current_user


def _run_async_in_thread(coro):
    result_container = {}
    exception_container = {}

    def _runner():
        loop = asyncio.new_event_loop()
        try:
            result_container["value"] = loop.run_until_complete(coro)
        except Exception as exc:
            exception_container["value"] = exc
        finally:
            loop.close()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join(timeout=60)

    if "value" in exception_container:
        raise exception_container["value"]
    if thread.is_alive():
        raise RuntimeError("查询超时（60秒）")
    return result_container.get("value")


def _build_operator_namespace(current_user_id):
    def query_table_data(datasource_id, table_name, **kwargs):
        args = {"datasource_id": str(datasource_id), "table_name": table_name, **kwargs}

        async def _run():
            async with async_session() as db:
                ctx = AgentContext(db=db, user_id=current_user_id)
                return await agent_service._query_table_data(args, ctx)

        result = json.loads(_run_async_in_thread(_run()))
        if isinstance(result, dict) and "rows" in result and "columns" in result:
            return pd.DataFrame(result["rows"], columns=result["columns"])
        if isinstance(result, dict) and "error" in result:
            raise RuntimeError(result["error"])
        return result

    def get_table_schema(datasource_id, table_name):
        args = {"datasource_id": str(datasource_id), "table_name": table_name}

        async def _run():
            async with async_session() as db:
                ctx = AgentContext(db=db, user_id=current_user_id)
                return await agent_service._get_table_schema(args, ctx)

        return json.loads(_run_async_in_thread(_run()))

    def get_datasource_id_by_name(name):
        async def _run():
            async with async_session() as db:
                from sqlalchemy import select as _select
                from app.models.datasource import DataSource as _DS
                result = await db.execute(_select(_DS).where(_DS.name == name))
                ds = result.scalar_one_or_none()
                if ds is None:
                    return json.dumps({"error": f"未找到数据源: {name}"})
                return json.dumps({"id": str(ds.id), "name": ds.name, "type": ds.type})

        result = json.loads(_run_async_in_thread(_run()))
        if "error" in result:
            raise RuntimeError(result["error"])
        return result["id"]

    return {
        "query_table_data": query_table_data,
        "get_table_schema": get_table_schema,
        "get_datasource_id_by_name": get_datasource_id_by_name,
        "pd": pd,
        "json": json,
    }

router = APIRouter()


@router.post("/upload", response_model=OperatorResponse, status_code=status.HTTP_201_CREATED)
async def upload_operator(
    file: UploadFile = File(...),
    category: Optional[str] = None,
    display_name: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传Python脚本，自动解析生成算子"""
    if not file.filename or not file.filename.lower().endswith(".py"):
        raise HTTPException(status_code=400, detail="请上传.py文件")

    script_content = (await file.read()).decode("utf-8")

    try:
        parsed = parse_python_script(script_content)
    except SyntaxError as e:
        raise HTTPException(status_code=400, detail=f"Python脚本语法错误: {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"脚本解析失败: {e}")

    func_name = parsed.get("function_name")
    if not func_name:
        raise HTTPException(status_code=400, detail="脚本中未找到可用的函数定义")

    script_name = extract_script_name(file.filename)

    operator = Operator(
        name=script_name,
        display_name=display_name or func_name,
        description=parsed.get("description") or script_name,
        category=category or "custom",
        inputs=parsed.get("inputs", [{"name": "data", "type": "DataFrame", "required": True}]),
        outputs=parsed.get("outputs", [{"name": "result", "type": "any"}]),
        parameters=parsed.get("parameters", []),
        execution_config={"type": "python_script"},
        script_content=script_content,
        script_filename=file.filename,
        function_name=func_name,
        tags=[],
        visibility="private",
        author=current_user.id,
    )
    db.add(operator)
    await db.flush()
    await db.refresh(operator)
    return operator


@router.get("/download/{operator_id}")
async def download_operator(
    operator_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """下载算子Python脚本"""
    result = await db.execute(select(Operator).where(Operator.id == operator_id))
    operator = result.scalar_one_or_none()
    if not operator:
        raise HTTPException(status_code=404, detail="算子不存在")

    if not operator.script_content:
        raise HTTPException(status_code=404, detail="该算子没有可下载的脚本")

    filename = operator.script_filename or f"{operator.name}.py"
    content = operator.script_content.encode("utf-8")

    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/x-python-code",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{operator_id}/debug", response_model=OperatorDebugResponse)
async def debug_operator(
    operator_id: UUID,
    request: OperatorDebugRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """调试执行算子"""
    result = await db.execute(select(Operator).where(Operator.id == operator_id))
    operator = result.scalar_one_or_none()
    if not operator:
        raise HTTPException(status_code=404, detail="算子不存在")

    if not operator.script_content:
        raise HTTPException(status_code=400, detail="该算子没有可执行的脚本")

    start_time = time.time()

    captured_output = io.StringIO()

    try:
        local_ns = {"__builtins__": __builtins__, "print": lambda *a, **kw: print(*a, file=captured_output, **kw)}
        local_ns.update(_build_operator_namespace(current_user.id))

        exec(operator.script_content, local_ns)

        func = local_ns.get(operator.function_name or "")
        if not func:
            raise ValueError(f"脚本中未找到函数: {operator.function_name}，可用函数: {[k for k in local_ns if callable(local_ns[k]) and not k.startswith('_')]}")

        params = request.parameters or {}

        is_async = inspect.iscoroutinefunction(func)

        if request.test_data is not None:
            if isinstance(request.test_data, list):
                test_data = pd.DataFrame(request.test_data)
            elif isinstance(request.test_data, dict):
                test_data = pd.DataFrame([request.test_data])
            else:
                test_data = request.test_data
            result_value = await func(test_data, **params) if is_async else func(test_data, **params)
        else:
            result_value = await func(**params) if is_async else func(**params)

        if hasattr(result_value, "to_dict"):
            result_value = result_value.to_dict(orient="records")

        elapsed = (time.time() - start_time) * 1000

        return OperatorDebugResponse(
            success=True,
            result=result_value,
            stdout=captured_output.getvalue() or None,
            execution_time_ms=round(elapsed, 2),
        )
    except Exception as e:
        elapsed = (time.time() - start_time) * 1000
        return OperatorDebugResponse(
            success=False,
            error=f"{type(e).__name__}: {str(e)}\n\n{traceback.format_exc()}",
            stdout=captured_output.getvalue() or None,
            execution_time_ms=round(elapsed, 2),
        )


@router.put("/{operator_id}/script", response_model=OperatorResponse)
async def update_operator_script(
    operator_id: UUID,
    request: OperatorScriptUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新算子脚本内容（会重新解析入参出参）"""
    result = await db.execute(select(Operator).where(Operator.id == operator_id))
    operator = result.scalar_one_or_none()
    if not operator:
        raise HTTPException(status_code=404, detail="算子不存在")

    try:
        parsed = parse_python_script(request.script_content)
    except SyntaxError as e:
        raise HTTPException(status_code=400, detail=f"Python脚本语法错误: {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"脚本解析失败: {e}")

    func_name = parsed.get("function_name")
    if not func_name:
        raise HTTPException(status_code=400, detail="脚本中未找到可用的函数定义")

    operator.script_content = request.script_content
    operator.function_name = func_name
    operator.inputs = parsed.get("inputs", operator.inputs)
    operator.outputs = parsed.get("outputs", operator.outputs)
    operator.parameters = parsed.get("parameters", operator.parameters)
    operator.description = parsed.get("description") or operator.description

    await db.flush()
    await db.refresh(operator)
    return operator


@router.post("", response_model=OperatorResponse, status_code=status.HTTP_201_CREATED)
async def create_operator(
    request: OperatorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建算子（手动方式）"""
    operator = Operator(
        name=request.name,
        display_name=request.display_name,
        description=request.description,
        category=request.category,
        inputs=request.inputs,
        outputs=request.outputs,
        parameters=request.parameters,
        execution_config=request.execution_config,
        code_template=request.code_template,
        tags=request.tags,
        visibility=request.visibility,
        author=current_user.id,
    )
    db.add(operator)
    await db.flush()
    await db.refresh(operator)
    return operator


@router.get("", response_model=list[OperatorResponse])
async def list_operators(
    category: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取算子列表"""
    query = select(Operator).where((Operator.author == current_user.id) | (Operator.visibility == "public"))
    if category:
        query = query.where(Operator.category == category)
    query = query.order_by(Operator.updated_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/categories", response_model=list[str])
async def get_categories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取算子分类"""
    result = await db.execute(
        select(Operator.category).distinct().where(Operator.category.isnot(None))
    )
    return [row[0] for row in result.all()]


@router.get("/{operator_id}", response_model=OperatorResponse)
async def get_operator(
    operator_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取算子详情"""
    result = await db.execute(select(Operator).where(Operator.id == operator_id))
    operator = result.scalar_one_or_none()
    if not operator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="算子不存在")
    return operator


@router.put("/{operator_id}", response_model=OperatorResponse)
async def update_operator(
    operator_id: UUID,
    request: OperatorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新算子"""
    result = await db.execute(select(Operator).where(Operator.id == operator_id))
    operator = result.scalar_one_or_none()
    if not operator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="算子不存在")

    update_data = request.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(operator, key, value)

    await db.flush()
    await db.refresh(operator)
    return operator


@router.delete("/{operator_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_operator(
    operator_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除算子"""
    result = await db.execute(select(Operator).where(Operator.id == operator_id))
    operator = result.scalar_one_or_none()
    if not operator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="算子不存在")
    await db.delete(operator)
    await db.flush()


@router.post("/{operator_id}/clone", response_model=OperatorResponse, status_code=status.HTTP_201_CREATED)
async def clone_operator(
    operator_id: UUID,
    request: OperatorCloneRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """另存为：复制算子及脚本"""
    result = await db.execute(select(Operator).where(Operator.id == operator_id))
    operator = result.scalar_one_or_none()
    if not operator:
        raise HTTPException(status_code=404, detail="算子不存在")

    script_name = request.name.lower().replace(" ", "_")

    clone = Operator(
        name=script_name,
        display_name=request.name,
        description=operator.description,
        category=operator.category,
        inputs=operator.inputs,
        outputs=operator.outputs,
        parameters=operator.parameters,
        execution_config=operator.execution_config,
        script_content=operator.script_content,
        script_filename=f"{script_name}.py",
        function_name=operator.function_name,
        tags=[*((operator.tags or []))],
        visibility=operator.visibility,
        author=current_user.id,
    )
    db.add(clone)
    await db.flush()
    await db.refresh(clone)
    return clone


SYSTEM_PROMPT = """你是一个专业的Python数据算子脚本生成器。你的任务是根据用户的自然语言描述，生成一个可执行的Python脚本。

规则：
1. 脚本必须包含一个主函数（入口函数），函数名要有意义（如 process_data, filter_data, analyze_data 等）
2. 函数必须有类型注解（type hints）和完整的docstring
3. 函数参数应该包含数据输入参数和配置参数，都要有合理的默认值
4. 脚本中可以定义辅助函数和导入必要的库
5. 只输出Python代码，不要任何解释文字，不要markdown代码块标记（不要```python和```），直接输出纯代码

## 内置工具函数（脚本中直接使用，无需 import）
- query_table_data(datasource_id, table_name, **kwargs) -> DataFrame: 从数据源查询表数据，返回 pandas DataFrame
- get_table_schema(datasource_id, table_name) -> dict: 获取表结构信息
- get_datasource_id_by_name(name) -> str: 根据数据源名称获取UUID
- pd (pandas) 和 json 已内置，无需再 import

⚠️ **绝对禁止** `import datacrab` 或 `from datacrab import ...`，datacrab 包不存在！
⚠️ **绝对禁止** `pip install datacrab`，datacrab 不是可安装的包！
⚠️ 上述工具函数由运行环境自动注入，脚本中直接使用即可

🚫 安全红线（必须遵守）：
- 算子只能处理用户的业务数据，绝不能修改 DataCrab 平台自身
- 不得生成访问或修改平台系统表（users, roles, permissions等）的代码
- 不得生成修改平台源代码、配置文件的代码
- 算子脚本中只能操作用户的业务数据，不能操作平台系统数据

✅ 算子属于用户内容，可以自由创建和修改：
- 用户可以自由创建、修改、调试、删除自己的算子脚本
- 算子脚本可以使用内置工具函数访问用户数据

✅ 修改后必验证（必须遵守）：
- 生成或修改脚本后，必须在脚本末尾添加自测逻辑：if __name__ == "__main__" 块中用示例数据调用主函数
- 自测逻辑应使用少量测试数据（如3-5行），验证主函数能正常执行并返回预期结果
- 如果自测失败，在输出中说明失败原因和修复建议

✅ 输出默认同源（必须遵守）：
- 数据处理生成新文件时，如果用户未指定输出路径（output_dir），默认保存到 DataSource（数据源）指定的文件路径下（即 connection_config.file_path 所在目录）
- 如果 DataSource 来自数据库而非文件，需要用户明确指定输出路径

输出格式：直接输出纯Python代码，第一个字符必须是import或def等Python关键字。"""


@router.post("/generate", response_model=OperatorResponse, status_code=status.HTTP_201_CREATED)
async def generate_operator(
    request: OperatorGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """根据自然语言描述生成算子"""
    await llm_manager.initialize()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": request.prompt},
    ]

    try:
        raw_code = await llm_manager.chat_with_messages(messages, temperature=0.3, max_tokens=3000)
    except Exception as e:
        logger.error(f"LLM生成算子失败: {e}")
        raise HTTPException(status_code=500, detail=f"AI生成失败: {str(e)}")

    script_content = raw_code.strip()
    if script_content.startswith("```"):
        lines = script_content.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        script_content = "\n".join(lines).strip()

    try:
        parsed = parse_python_script(script_content)
    except SyntaxError as e:
        logger.warning(f"生成的脚本语法错误，尝试自动修复: {e}")
        fix_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": request.prompt},
            {"role": "assistant", "content": raw_code},
            {"role": "user", "content": f"上面的代码有语法错误：{e}。请修复并重新输出完整的纯Python代码。注意：不要使用中文标点符号（如中文逗号、中文冒号），所有标点必须是英文半角。"},
        ]
        try:
            fixed_code = await llm_manager.chat_with_messages(fix_messages, temperature=0.2, max_tokens=3000)
            script_content = fixed_code.strip()
            if script_content.startswith("```"):
                lines = script_content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                script_content = "\n".join(lines).strip()
            parsed = parse_python_script(script_content)
        except Exception as fix_err:
            raise HTTPException(status_code=400, detail=f"生成脚本语法错误且自动修复失败: {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"生成脚本解析失败: {e}")

    func_name = parsed.get("function_name")
    if not func_name:
        raise HTTPException(status_code=400, detail="生成的脚本中未找到可用的函数定义")

    script_name = func_name.replace("_", " ").title().replace(" ", "_").lower()

    operator = Operator(
        name=script_name,
        display_name=parsed.get("description") or func_name,
        description=parsed.get("description") or script_name,
        category="ai_generated",
        inputs=parsed.get("inputs", [{"name": "data", "type": "DataFrame", "required": True}]),
        outputs=parsed.get("outputs", [{"name": "result", "type": "any"}]),
        parameters=parsed.get("parameters", []),
        execution_config={"type": "python_script"},
        script_content=script_content,
        script_filename=f"{script_name}.py",
        function_name=func_name,
        tags=["ai_generated"],
        visibility="private",
        author=current_user.id,
    )
    db.add(operator)
    await db.flush()
    await db.refresh(operator)

    try:
        local_ns = {"__builtins__": __builtins__}
        local_ns.update(_build_operator_namespace(current_user.id))
        exec(script_content, local_ns)
        logger.info(f"算子生成后自动验证通过: {script_name}")
    except Exception as e:
        logger.warning(f"算子生成后自动验证失败（不影响保存）: {e}")

    return operator


@router.post("/{operator_id}/modify", response_model=OperatorResponse)
async def modify_operator(
    operator_id: UUID,
    request: OperatorModifyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """根据自然语言指令修改算子脚本"""
    result = await db.execute(select(Operator).where(Operator.id == operator_id))
    operator = result.scalar_one_or_none()
    if not operator:
        raise HTTPException(status_code=404, detail="算子不存在")

    if not operator.script_content:
        raise HTTPException(status_code=400, detail="该算子没有可修改的脚本")

    await llm_manager.initialize()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"以下是现有算子的脚本代码：\n\n```python\n{operator.script_content}\n```\n\n请根据以下要求修改这个算子：\n{request.instruction}\n\n请输出修改后的完整脚本代码。"},
    ]

    try:
        raw_code = await llm_manager.chat_with_messages(messages, temperature=0.3, max_tokens=3000)
    except Exception as e:
        logger.error(f"LLM修改算子失败: {e}")
        raise HTTPException(status_code=500, detail=f"AI修改失败: {str(e)}")

    script_content = raw_code.strip()
    if script_content.startswith("```"):
        lines = script_content.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        script_content = "\n".join(lines).strip()

    try:
        parsed = parse_python_script(script_content)
    except SyntaxError as e:
        logger.warning(f"修改后的脚本语法错误，尝试自动修复: {e}")
        fix_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"以下是现有算子的脚本代码：\n\n```python\n{operator.script_content}\n```\n\n请根据以下要求修改这个算子：\n{request.instruction}"},
            {"role": "assistant", "content": raw_code},
            {"role": "user", "content": f"上面的代码有语法错误：{e}。请修复并重新输出完整的纯Python代码。注意：不要使用中文标点符号，所有标点必须是英文半角。"},
        ]
        try:
            fixed_code = await llm_manager.chat_with_messages(fix_messages, temperature=0.2, max_tokens=3000)
            script_content = fixed_code.strip()
            if script_content.startswith("```"):
                lines = script_content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                script_content = "\n".join(lines).strip()
            parsed = parse_python_script(script_content)
        except Exception as fix_err:
            raise HTTPException(status_code=400, detail=f"修改后脚本语法错误且自动修复失败: {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"修改后脚本解析失败: {e}")

    func_name = parsed.get("function_name")
    if not func_name:
        raise HTTPException(status_code=400, detail="修改后的脚本中未找到可用的函数定义")

    operator.script_content = script_content
    operator.function_name = func_name
    operator.inputs = parsed.get("inputs", operator.inputs)
    operator.outputs = parsed.get("outputs", operator.outputs)
    operator.parameters = parsed.get("parameters", operator.parameters)

    try:
        desc_messages = [
            {"role": "system", "content": "你是一个算子描述生成器。根据算子脚本和修改指令，生成简洁的算子描述。只输出描述文本，不要任何解释。"},
            {"role": "user", "content": f"原始描述：{operator.description}\n修改指令：{request.instruction}\n修改后的脚本：\n{script_content}\n\n请生成更新后的算子描述（一句话概括功能）和显示名称。格式：\n描述：...\n名称：..."},
        ]
        desc_result = await llm_manager.chat_with_messages(desc_messages, temperature=0.3, max_tokens=200)
        if desc_result:
            for line in desc_result.strip().split("\n"):
                line = line.strip()
                if line.startswith("描述：") or line.startswith("描述:"):
                    operator.description = line.split("：", 1)[-1].split(":", 1)[-1].strip() or operator.description
                elif line.startswith("名称：") or line.startswith("名称:"):
                    operator.display_name = line.split("：", 1)[-1].split(":", 1)[-1].strip() or operator.display_name
    except Exception as e:
        logger.warning(f"生成算子描述失败，保留原描述: {e}")
        operator.description = parsed.get("description") or operator.description

    await db.flush()
    await db.refresh(operator)

    try:
        local_ns = _build_operator_namespace(current_user.id)
        exec(script_content, local_ns)
        test_func = local_ns.get(func_name)
        if test_func and not inspect.iscoroutinefunction(test_func):
            sig = inspect.signature(test_func)
            test_params = {}
            for pname, param in sig.parameters.items():
                if param.default is inspect.Parameter.empty and pname not in local_ns:
                    if param.annotation in (pd.DataFrame, "DataFrame") or pname in ("data", "df", "input_data"):
                        test_params[pname] = pd.DataFrame([{"test": 1}])
                    else:
                        test_params[pname] = None
            test_func(**test_params)
            logger.info(f"算子修改后自动验证通过: {operator.name}")
    except Exception as e:
        logger.warning(f"算子修改后自动验证失败（不影响保存）: {e}")

    return operator