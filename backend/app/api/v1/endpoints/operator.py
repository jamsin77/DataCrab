"""算子管理API端点"""

import io
import time
import traceback
import sys
import json
import inspect
from uuid import UUID
from typing import Optional

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
    OperatorDebugChatRequest,
)
from app.services.operator_parser import parse_python_script, extract_script_name
from app.services.llm import llm_manager
from app.services import experience
from app.services.sandbox_ns import build_operator_namespace as _build_operator_namespace, run_async_in_thread as _run_async_in_thread
from app.services.prompt_docs import SANDBOX_TOOLS_DOC, SAFETY_RULES_DOC
from app.api.deps import get_current_user


async def _system_prompt_with_lessons(db: AsyncSession, current_user: User) -> str:
    """构建注入经验库的算子生成系统提示词。"""
    lessons = await experience.collect_all_lessons(db, current_user.id)
    if lessons:
        return (
            SYSTEM_PROMPT
            + "\n\n## 📖 历史经验库（从过往失败中归纳的经验，生成脚本时务必参考，避免重蹈覆辙）\n"
            + lessons[:2000]
        )
    return SYSTEM_PROMPT


def _validate_operator_script(script_content: str, current_user_id) -> tuple[bool, str]:
    """验证算子脚本是否可正常加载，返回 (成功, 错误信息)"""
    try:
        local_ns = _build_operator_namespace(current_user_id)
        exec(script_content, local_ns)
        return True, ""
    except SyntaxError as e:
        return False, f"语法错误 (行{e.lineno}): {e.msg}"
    except Exception as e:
        return False, f"执行错误: {type(e).__name__}: {e}"


async def _llm_fix_operator_script(
    original_prompt_messages: list, broken_code: str, error_msg: str
) -> str:
    """用 LLM 修复有问题的算子脚本，返回修复后的代码"""
    fix_messages = original_prompt_messages + [
        {"role": "assistant", "content": broken_code},
        {"role": "user", "content": (
            f"上面的代码运行出错：{error_msg}\n\n"
            "请修复并重新输出完整的纯Python代码。注意：\n"
            "1. 不要使用中文标点符号，所有标点必须是英文半角\n"
            "2. 确保所有变量在使用前已定义\n"
            "3. 确保 import 语句完整\n"
            "4. 直接输出纯代码，不要markdown代码块标记"
        )},
    ]
    fixed_code = await llm_manager.chat_with_messages(fix_messages, temperature=0.2, max_tokens=3000)
    script_content = fixed_code.strip()
    if script_content.startswith("```"):
        lines = script_content.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        script_content = "\n".join(lines).strip()
    return script_content


def _strip_code_fences(raw_code: str) -> str:
    """去除 LLM 输出中的 markdown 代码块标记"""
    script_content = raw_code.strip()
    if script_content.startswith("```"):
        lines = script_content.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        script_content = "\n".join(lines).strip()
    return script_content


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
    import pandas as pd
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

        # 经验采集（非侵入式）
        from app.services.data_harness import collect_experience
        collect_experience(
            experience.operator_experience_dir(operator_id),
            source="debug",
            exec_result={"success": True, "result": result_value, "stdout": captured_output.getvalue()},
            parameters=request.parameters or {},
            script_name=operator.function_name or "",
        )

        return OperatorDebugResponse(
            success=True,
            result=result_value,
            stdout=captured_output.getvalue() or None,
            execution_time_ms=round(elapsed, 2),
        )
    except Exception as e:
        elapsed = (time.time() - start_time) * 1000
        # 经验采集（非侵入式）
        from app.services.data_harness import collect_experience
        collect_experience(
            experience.operator_experience_dir(operator_id),
            source="debug",
            exec_result={"success": False, "error": f"{type(e).__name__}: {str(e)}", "stdout": captured_output.getvalue()},
            parameters=request.parameters or {},
            script_name=operator.function_name or "",
        )
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
    sort_by: str = Query("created", pattern="^(created|updated)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取算子列表"""
    from app.services.permission_service import get_accessible_resource_ids
    shared_ids = await get_accessible_resource_ids(db, current_user.id, "operator")
    query = select(Operator).where(
        or_(
            Operator.author == current_user.id,
            Operator.visibility == "public",
            Operator.id.in_(shared_ids) if shared_ids else False,
        )
    )
    if category:
        query = query.where(Operator.category == category)
    order_col = Operator.updated_at if sort_by == "updated" else Operator.created_at
    query = query.order_by(order_col.desc()).offset(skip).limit(limit)
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

## 输出规则
1. 脚本必须包含一个主函数（入口函数），函数名要有意义（如 process_data, filter_data, analyze_data 等）
2. 函数必须有类型注解（type hints）和完整的docstring
3. 函数参数应该包含数据输入参数和配置参数，都要有合理的默认值
4. 脚本中可以定义辅助函数和导入必要的库
5. 只输出Python代码，不要任何解释文字，不要markdown代码块标记（不要```python和```），直接输出纯代码
6. 输出格式：直接输出纯Python代码，第一个字符必须是import或def等Python关键字

""" + SANDBOX_TOOLS_DOC + """

## 编码最佳实践
1. 主函数通过 get_datasource_id_by_name() 获取数据源ID，再通过 query_table_data() 读取数据
2. 使用 pandas 进行数据处理，优先使用向量化操作而非循环
3. 处理边界情况：空DataFrame、列不存在、空值、类型转换失败
4. 用 print() 输出关键处理步骤和结果摘要
5. 有意义的返回值：返回 dict 包含 success/status/data/message 等字段

## 示例

用户需求："筛选出价格大于100的商品"

import pandas as pd
from typing import Dict, Any, Optional

def filter_expensive_products(
    datasource_name: str = "商品数据",
    table_name: str = "products",
    min_price: float = 100.0,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    \"\"\"
    筛选价格大于指定阈值的商品

    Parameters
    ----------
    datasource_name : str
        数据源名称
    table_name : str
        表名
    min_price : float
        最低价格阈值，默认100.0
    output_dir : Optional[str]
        输出目录，默认为数据源文件所在目录

    Returns
    -------
    Dict[str, Any]
        包含 success, filtered_count, data 的结果
    \"\"\"
    ds_id = get_datasource_id_by_name(datasource_name)
    if not ds_id:
        raise ValueError(f"找不到数据源: {datasource_name}")

    df = query_table_data(ds_id, table_name)
    if df.empty:
        print(f"⚠️ 表 '{table_name}' 无数据")
        return {"success": True, "filtered_count": 0, "data": []}

    price_col = None
    for col in df.columns:
        if "价格" in col or "price" in col.lower():
            price_col = col
            break

    if price_col is None:
        raise ValueError(f"未找到价格列，现有列: {list(df.columns)}")

    df[price_col] = pd.to_numeric(df[price_col], errors="coerce")
    filtered = df[df[price_col] > min_price].copy()

    print(f"✅ 筛选完成: {len(df)} 行 → {len(filtered)} 行 (价格 > {min_price})")

    if output_dir:
        import os
        output_path = os.path.join(output_dir, f"filtered_{table_name}.csv")
        filtered.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"📁 结果已保存: {output_path}")

    return {
        "success": True,
        "filtered_count": len(filtered),
        "columns": list(filtered.columns),
        "data": filtered.to_dict(orient="records")[:10],
    }


if __name__ == "__main__":
    result = filter_expensive_products(min_price=100.0)
    print(f"结果: {result}")

""" + SAFETY_RULES_DOC


@router.post("/generate", response_model=OperatorResponse, status_code=status.HTTP_201_CREATED)
async def generate_operator(
    request: OperatorGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """根据自然语言描述生成算子"""
    await llm_manager.initialize()
    sys_prompt = await _system_prompt_with_lessons(db, current_user)

    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": request.prompt},
    ]

    try:
        raw_code = await llm_manager.chat_with_messages(messages, temperature=0.3, max_tokens=3000)
    except Exception as e:
        logger.error(f"LLM生成算子失败: {e}")
        raise HTTPException(status_code=500, detail=f"AI生成失败: {str(e)}")

    script_content = _strip_code_fences(raw_code)

    MAX_FIX_ROUNDS = 2
    for fix_round in range(MAX_FIX_ROUNDS + 1):
        try:
            parsed = parse_python_script(script_content)
            break
        except SyntaxError as e:
            if fix_round >= MAX_FIX_ROUNDS:
                raise HTTPException(status_code=400, detail=f"生成脚本语法错误且自动修复失败: {e}")
            logger.warning(f"生成的脚本语法错误(修复第{fix_round+1}轮): {e}")
            try:
                script_content = await _llm_fix_operator_script(messages, script_content, f"语法错误: {e}")
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

    success, error_msg = _validate_operator_script(script_content, current_user.id)
    if success:
        logger.info(f"算子生成后自动验证通过: {script_name}")
    else:
        logger.warning(f"算子生成后自动验证失败: {error_msg}，尝试LLM修复...")
        for fix_round in range(MAX_FIX_ROUNDS):
            try:
                prompt_messages = [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": request.prompt},
                ]
                fixed_content = await _llm_fix_operator_script(prompt_messages, script_content, error_msg)
                parsed2 = parse_python_script(fixed_content)
                success2, error2 = _validate_operator_script(fixed_content, current_user.id)
                if success2:
                    operator.script_content = fixed_content
                    operator.function_name = parsed2.get("function_name", func_name)
                    logger.info(f"算子生成后LLM修复验证通过(第{fix_round+1}轮): {script_name}")
                    break
                else:
                    script_content = fixed_content
                    error_msg = error2
                    logger.warning(f"算子生成后LLM修复验证仍失败(第{fix_round+1}轮): {error2}")
            except Exception as e:
                logger.warning(f"算子生成后LLM修复异常(第{fix_round+1}轮): {e}")
                break

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
    sys_prompt = await _system_prompt_with_lessons(db, current_user)

    user_msg = f"以下是现有算子的脚本代码：\n\n```python\n{operator.script_content}\n```\n\n请根据以下要求修改这个算子：\n{request.instruction}\n\n请输出修改后的完整脚本代码。"
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_msg},
    ]

    try:
        raw_code = await llm_manager.chat_with_messages(messages, temperature=0.3, max_tokens=3000)
    except Exception as e:
        logger.error(f"LLM修改算子失败: {e}")
        raise HTTPException(status_code=500, detail=f"AI修改失败: {str(e)}")

    script_content = _strip_code_fences(raw_code)

    MAX_FIX_ROUNDS = 2
    for fix_round in range(MAX_FIX_ROUNDS + 1):
        try:
            parsed = parse_python_script(script_content)
            break
        except SyntaxError as e:
            if fix_round >= MAX_FIX_ROUNDS:
                raise HTTPException(status_code=400, detail=f"修改后脚本语法错误且自动修复失败: {e}")
            logger.warning(f"修改后的脚本语法错误(修复第{fix_round+1}轮): {e}")
            try:
                script_content = await _llm_fix_operator_script(messages, script_content, f"语法错误: {e}")
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

    success, error_msg = _validate_operator_script(script_content, current_user.id)
    if success:
        logger.info(f"算子修改后自动验证通过: {operator.name}")
    else:
        logger.warning(f"算子修改后自动验证失败: {error_msg}，尝试LLM修复...")
        for fix_round in range(MAX_FIX_ROUNDS):
            try:
                fixed_content = await _llm_fix_operator_script(messages, script_content, error_msg)
                parsed2 = parse_python_script(fixed_content)
                success2, error2 = _validate_operator_script(fixed_content, current_user.id)
                if success2:
                    operator.script_content = fixed_content
                    operator.function_name = parsed2.get("function_name", func_name)
                    await db.flush()
                    logger.info(f"算子修改后LLM修复验证通过(第{fix_round+1}轮): {operator.name}")
                    break
                else:
                    script_content = fixed_content
                    error_msg = error2
                    logger.warning(f"算子修改后LLM修复验证仍失败(第{fix_round+1}轮): {error2}")
            except Exception as e:
                logger.warning(f"算子修改后LLM修复异常(第{fix_round+1}轮): {e}")
                break

    return operator


@router.post("/generate-stream")
async def generate_operator_stream(
    request: OperatorGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await llm_manager.initialize()
    sys_prompt = await _system_prompt_with_lessons(db, current_user)
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": request.prompt},
    ]

    async def generate():
        import json as json_mod
        full_content = ""
        try:
            yield f"data: {json_mod.dumps({'type': 'phase', 'phase': 'generating', 'message': 'AI 正在推理和生成算子代码...'}, ensure_ascii=False)}\n\n"

            async for chunk in llm_manager.chat_stream_with_thinking(messages, temperature=0.3):
                if chunk["type"] == "thinking":
                    yield f"data: {json_mod.dumps({'type': 'thinking', 'content': chunk['content']}, ensure_ascii=False)}\n\n"
                elif chunk["type"] == "content":
                    full_content += chunk["content"]
                    yield f"data: {json_mod.dumps({'type': 'content', 'content': chunk['content']}, ensure_ascii=False)}\n\n"

            raw_code = full_content.strip()
            script_content = _strip_code_fences(raw_code)

            yield f"data: {json_mod.dumps({'type': 'phase', 'phase': 'parsing', 'message': '解析生成的脚本...'}, ensure_ascii=False)}\n\n"

            MAX_FIX_ROUNDS = 2
            for fix_round in range(MAX_FIX_ROUNDS + 1):
                try:
                    parsed = parse_python_script(script_content)
                    break
                except SyntaxError as e:
                    if fix_round >= MAX_FIX_ROUNDS:
                        yield f"data: {json_mod.dumps({'type': 'error', 'content': f'生成脚本语法错误且自动修复失败: {e}'}, ensure_ascii=False)}\n\n"
                        return
                    yield f"data: {json_mod.dumps({'type': 'phase', 'phase': 'fixing', 'message': f'语法错误，自动修复(第{fix_round+1}轮)...'}, ensure_ascii=False)}\n\n"
                    try:
                        script_content = await _llm_fix_operator_script(messages, script_content, f"语法错误: {e}")
                    except Exception:
                        yield f"data: {json_mod.dumps({'type': 'error', 'content': f'生成脚本语法错误且自动修复失败: {e}'}, ensure_ascii=False)}\n\n"
                        return
                except Exception as e:
                    yield f"data: {json_mod.dumps({'type': 'error', 'content': f'生成脚本解析失败: {e}'}, ensure_ascii=False)}\n\n"
                    return

            func_name = parsed.get("function_name")
            if not func_name:
                yield f"data: {json_mod.dumps({'type': 'error', 'content': '生成的脚本中未找到可用的函数定义'}, ensure_ascii=False)}\n\n"
                return

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

            yield f"data: {json_mod.dumps({'type': 'phase', 'phase': 'validating', 'message': '验证生成的算子...'}, ensure_ascii=False)}\n\n"

            success, error_msg = _validate_operator_script(script_content, current_user.id)
            if not success:
                yield f"data: {json_mod.dumps({'type': 'phase', 'phase': 'fixing', 'message': '验证失败，尝试自动修复...'}, ensure_ascii=False)}\n\n"
                for fix_round in range(MAX_FIX_ROUNDS):
                    try:
                        prompt_messages = [
                            {"role": "system", "content": sys_prompt},
                            {"role": "user", "content": request.prompt},
                        ]
                        fixed_content = await _llm_fix_operator_script(prompt_messages, script_content, error_msg)
                        parsed2 = parse_python_script(fixed_content)
                        success2, error2 = _validate_operator_script(fixed_content, current_user.id)
                        if success2:
                            operator.script_content = fixed_content
                            operator.function_name = parsed2.get("function_name", func_name)
                            await db.flush()
                            break
                        else:
                            script_content = fixed_content
                            error_msg = error2
                    except Exception:
                        break

            from app.schemas.operator import OperatorResponse as OpRes
            op_data = OpRes.model_validate(operator).model_dump()
            yield f"data: {json_mod.dumps({'type': 'done', 'operator': _sanitize_op(op_data)}, ensure_ascii=False, default=str)}\n\n"

        except asyncio.CancelledError:
            yield f"data: {json_mod.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"流式生成算子失败: {e}")
            yield f"data: {json_mod.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@router.post("/{operator_id}/modify-stream")
async def modify_operator_stream(
    operator_id: UUID,
    request: OperatorModifyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Operator).where(Operator.id == operator_id))
    operator = result.scalar_one_or_none()
    if not operator:
        raise HTTPException(status_code=404, detail="算子不存在")
    if not operator.script_content:
        raise HTTPException(status_code=400, detail="该算子没有可修改的脚本")

    await llm_manager.initialize()
    sys_prompt = await _system_prompt_with_lessons(db, current_user)

    user_msg = f"以下是现有算子的脚本代码：\n\n```python\n{operator.script_content}\n```\n\n请根据以下要求修改这个算子：\n{request.instruction}\n\n请输出修改后的完整脚本代码。"
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_msg},
    ]

    async def generate():
        import json as json_mod
        full_content = ""
        try:
            yield f"data: {json_mod.dumps({'type': 'phase', 'phase': 'modifying', 'message': 'AI 正在推理和修改算子代码...'}, ensure_ascii=False)}\n\n"

            async for chunk in llm_manager.chat_stream_with_thinking(messages, temperature=0.3):
                if chunk["type"] == "thinking":
                    yield f"data: {json_mod.dumps({'type': 'thinking', 'content': chunk['content']}, ensure_ascii=False)}\n\n"
                elif chunk["type"] == "content":
                    full_content += chunk["content"]
                    yield f"data: {json_mod.dumps({'type': 'content', 'content': chunk['content']}, ensure_ascii=False)}\n\n"

            raw_code = full_content.strip()
            script_content = _strip_code_fences(raw_code)

            yield f"data: {json_mod.dumps({'type': 'phase', 'phase': 'parsing', 'message': '解析修改后的脚本...'}, ensure_ascii=False)}\n\n"

            MAX_FIX_ROUNDS = 2
            for fix_round in range(MAX_FIX_ROUNDS + 1):
                try:
                    parsed = parse_python_script(script_content)
                    break
                except SyntaxError as e:
                    if fix_round >= MAX_FIX_ROUNDS:
                        yield f"data: {json_mod.dumps({'type': 'error', 'content': f'修改后脚本语法错误且自动修复失败: {e}'}, ensure_ascii=False)}\n\n"
                        return
                    yield f"data: {json_mod.dumps({'type': 'phase', 'phase': 'fixing', 'message': f'语法错误，自动修复(第{fix_round+1}轮)...'}, ensure_ascii=False)}\n\n"
                    try:
                        script_content = await _llm_fix_operator_script(messages, script_content, f"语法错误: {e}")
                    except Exception:
                        yield f"data: {json_mod.dumps({'type': 'error', 'content': f'修改后脚本语法错误且自动修复失败: {e}'}, ensure_ascii=False)}\n\n"
                        return
                except Exception as e:
                    yield f"data: {json_mod.dumps({'type': 'error', 'content': f'修改后脚本解析失败: {e}'}, ensure_ascii=False)}\n\n"
                    return

            func_name = parsed.get("function_name")
            if not func_name:
                yield f"data: {json_mod.dumps({'type': 'error', 'content': '修改后的脚本中未找到可用的函数定义'}, ensure_ascii=False)}\n\n"
                return

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
            except Exception:
                operator.description = parsed.get("description") or operator.description

            await db.flush()
            await db.refresh(operator)

            yield f"data: {json_mod.dumps({'type': 'phase', 'phase': 'validating', 'message': '验证修改后的算子...'}, ensure_ascii=False)}\n\n"

            success, error_msg = _validate_operator_script(script_content, current_user.id)
            if not success:
                yield f"data: {json_mod.dumps({'type': 'phase', 'phase': 'fixing', 'message': '验证失败，尝试自动修复...'}, ensure_ascii=False)}\n\n"
                for fix_round in range(MAX_FIX_ROUNDS):
                    try:
                        fixed_content = await _llm_fix_operator_script(messages, script_content, error_msg)
                        parsed2 = parse_python_script(fixed_content)
                        success2, error2 = _validate_operator_script(fixed_content, current_user.id)
                        if success2:
                            operator.script_content = fixed_content
                            operator.function_name = parsed2.get("function_name", func_name)
                            await db.flush()
                            break
                        else:
                            script_content = fixed_content
                            error_msg = error2
                    except Exception:
                        break

            await db.refresh(operator)
            from app.schemas.operator import OperatorResponse as OpRes
            op_data = OpRes.model_validate(operator).model_dump()
            yield f"data: {json_mod.dumps({'type': 'done', 'operator': _sanitize_op(op_data)}, ensure_ascii=False, default=str)}\n\n"

        except asyncio.CancelledError:
            yield f"data: {json_mod.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"流式修改算子失败: {e}")
            yield f"data: {json_mod.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@router.post("/{operator_id}/debug-chat")
async def debug_operator_chat(
    operator_id: UUID,
    request: OperatorDebugChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """算子 AI 调试助手（多智能体架构：DataProcessor + DataInspector）"""
    result = await db.execute(select(Operator).where(Operator.id == operator_id))
    operator = result.scalar_one_or_none()
    if not operator:
        raise HTTPException(status_code=404, detail="算子不存在")

    await llm_manager.initialize()

    script_content = operator.script_content or ""
    func_name = operator.function_name or ""
    display_name = operator.display_name or operator.name

    ctx = request.context or {}
    op_lessons = experience.read_lessons(experience.operator_experience_dir(operator_id)) or ""

    input_parts = []
    param_parts = []
    for k, v in ctx.items():
        if k.startswith("input_"):
            input_parts.append(f"{k}: {v}")
        elif k.startswith("param_"):
            param_parts.append(f"{k}: {v}")
    user_ctx = "\n".join(input_parts + param_parts)
    last_result = ctx.get("last_result", "")
    last_error = ctx.get("last_error", "")

    from app.services.multi_agent import AgentRuntime, AgentMessage, HandoffReason, agent_registry
    from app.services.data_processor_agent import DataProcessorAgent
    from app.services.data_inspector_agent import DataInspectorAgent

    if not agent_registry.get("data_processor"):
        agent_registry.register(DataProcessorAgent())
    if not agent_registry.get("data_inspector"):
        agent_registry.register(DataInspectorAgent())

    runtime = AgentRuntime(agent_registry, llm_manager)

    history = []
    for h in (request.history or [])[-10:]:
        history.append({"role": h.get("role", "user"), "content": h.get("content", "")[:500]})

    user_msg = request.message
    if user_ctx or last_result or last_error:
        user_msg += f"\n\n[当前调试上下文]"
        if user_ctx:
            user_msg += f"\n{user_ctx[:500]}"
        if last_result:
            user_msg += f"\n上次执行结果: {last_result}"
        if last_error:
            user_msg += f"\n上次错误: {last_error[:500]}"

    context = {
        "debug_mode": True,
        "debug_type": "operator",
        "db": db,
        "user_id": current_user.id,
        "history": history,
        "debug_operator_id": operator_id,
        "debug_script_name": func_name or "main",
        "debug_script_content": script_content,
        "debug_function_name": func_name,
        "debug_last_success_params": None,
        "debug_lessons": op_lessons,
        "debug_user_context": ctx,
        "debug_max_rounds": 7,"debug_max_inspections": 7,
    }

    message = AgentMessage(
        from_agent="user",
        to_agent="data_processor",
        reason=HandoffReason.DELEGATE,
        payload={"user_message": user_msg},
        context=context,
    )

    import json as json_mod

    async def generate():
        import asyncio
        from app.services.llm import init_user_llm_context
        await init_user_llm_context(current_user.id)

        runtime_gen = runtime.run("data_processor", message, context)

        _inspector_active = False
        _inspector_summary = ""
        _inspector_content_sent = False
        try:
            while True:
                try:
                    event = await asyncio.wait_for(runtime_gen.__anext__(), timeout=20.0)
                except asyncio.TimeoutError:
                    yield f"data: {json_mod.dumps({'type': 'ping'}, ensure_ascii=False)}\n\n"
                    continue
                except StopAsyncIteration:
                    break

                t = event.get("type")
                if t == "agent_switch":
                    agent = event.get("agent")
                    _inspector_active = (agent == "data_inspector")
                    if agent == "data_inspector":
                        evt = {"type": "inspecting", "message": "执行成功，DataInspector 正在检查数据质量..."}
                    elif agent == "data_processor":
                        _retry_round = context.get("debug_inspection_round", 0) + 1
                        evt = {"type": "retry", "round": _retry_round, "message": f"DataInspector 发现问题，第 {_retry_round} 轮修复..."}
                    else:
                        evt = None
                    if evt:
                        yield f"data: {json_mod.dumps(evt, ensure_ascii=False)}\n\n"
                elif t == "done":
                    if _inspector_active and _inspector_summary and not _inspector_content_sent:
                        yield f"data: {json_mod.dumps({'type': 'content', 'content': _inspector_summary}, ensure_ascii=False)}\n\n"
                    _inspector_active = False
                    yield f"data: {json_mod.dumps(event, ensure_ascii=False, default=str)}\n\n"
                elif _inspector_active and t == "warning_confirmation":
                    _inspector_summary = event.get("summary", "")
                elif _inspector_active and t == "content":
                    yield f"data: {json_mod.dumps(event, ensure_ascii=False, default=str)}\n\n"
                    _inspector_content_sent = True
                elif _inspector_active and t == "fatal":
                    _inspector_summary = event.get("summary", "") or "发现致命问题，已停止处理"
                elif _inspector_active and t == "tool_result":
                    pass
                else:
                    yield f"data: {json_mod.dumps(event, ensure_ascii=False, default=str)}\n\n"

            yield f"data: {json_mod.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            yield f"data: {json_mod.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"算子调试对话失败: {e}")
            yield f"data: {json_mod.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


def _sanitize_op(obj):
    import math
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_op(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_op(v) for v in obj]
    return obj


@router.get("/{operator_id}/experience")
async def get_operator_experience(
    operator_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查看算子经验库（反例列表 + 经验总结 + 统计）"""
    base = experience.operator_experience_dir(operator_id)
    return {
        "stats": experience.experience_stats(base),
        "negative": experience.read_negative(base),
        "positive": experience.read_positive(base),
        "lessons": experience.read_lessons(base),
    }


@router.post("/{operator_id}/summarize-experience")
async def summarize_operator_experience(
    operator_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """分析算子错误日志，用 LLM 归纳经验并写入经验库"""
    result = await db.execute(select(Operator).where(Operator.id == operator_id))
    operator = result.scalar_one_or_none()
    if not operator:
        raise HTTPException(status_code=404, detail="算子不存在")

    base = experience.operator_experience_dir(operator_id)
    errors = experience.read_negative(base)
    positives = experience.read_positive(base)
    if not errors and not positives:
        return {"success": True, "message": "暂无错误/成功记录", "error_count": 0, "lessons": ""}

    await llm_manager.initialize()

    import json as json_mod
    lines = []
    for i, e in enumerate(errors[-30:], 1):
        lines.append(
            f"{i}. [{e.get('timestamp','')[:10]}] {e.get('error_type','')}: "
            f"{e.get('error_message','')[:150]}"
        )
        if e.get("stdout_preview"):
            lines.append(f"   输出预览: {e['stdout_preview'][:100]}")
        if e.get("parameters"):
            lines.append(f"   参数: {json_mod.dumps(e['parameters'], ensure_ascii=False)[:100]}")

    pos_lines = []
    for i, p in enumerate(positives[-15:], 1):
        pos_lines.append(
            f"{i}. 参数: {json_mod.dumps(p.get('parameters', {}), ensure_ascii=False)[:120]}"
            f" → 结果摘要: {p.get('result_summary','')[:80]}"
        )

    existing = experience.read_lessons(base)
    lessons_ctx = f"\n\n已有的经验总结（在此基础上补充更新）：\n{existing}" if existing else ""

    prompt_messages = [
        {
            "role": "system",
            "content": (
                "你是一个算子经验分析专家。分析算子执行中的【错误日志（反例）】和【成功记录（正例）】，"
                "总结出规律性的经验。要求：\n"
                "1. 反例：按错误类型分类，给出问题描述、根因、修复建议\n"
                "2. 正例：归纳成功模式与最佳实践（哪些参数组合/写法能稳定成功）\n"
                "3. 如果已有经验总结，在此基础上补充更新（保留仍有效条目，更新已有条目，添加新发现）\n"
                "4. 使用 Markdown 格式，用 ### 分类别，分别有「常见错误」和「成功模式」两节\n"
                "5. 只输出经验总结内容，不要前言结尾\n"
                "6. 简洁精炼，每个条目不超过3行"
            ),
        },
        {
            "role": "user",
            "content": (
                f"算子名称：{operator.display_name or operator.name}\n"
                f"算子描述：{operator.description or '无'}\n"
                f"【反例·错误记录】（最近{len(errors[-30:])}条，共{len(errors)}条）：\n\n"
                + "\n".join(lines)
                + (f"\n\n【正例·成功记录】（最近{len(pos_lines)}条，共{len(positives)}条）：\n\n" + "\n".join(pos_lines) if pos_lines else "")
                + lessons_ctx
            ),
        },
    ]

    try:
        lessons_text = await llm_manager.chat_with_messages(
            prompt_messages, temperature=0.3, max_tokens=1500
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM总结失败: {str(e)}")

    experience.write_lessons(base, lessons_text.strip())

    return {
        "success": True,
        "message": f"已总结 {len(errors)} 条错误记录并更新经验库",
        "error_count": len(errors),
        "lessons": lessons_text.strip(),
    }


@router.post("/{operator_id}/to-pipeline-stream")
async def operator_to_pipeline_stream(
    operator_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """将算子脚本转为流程（SSE 流式，推送推理过程）"""
    result = await db.execute(select(Operator).where(Operator.id == operator_id))
    operator = result.scalar_one_or_none()
    if not operator:
        raise HTTPException(status_code=404, detail="算子不存在")

    if not operator.script_content:
        raise HTTPException(status_code=400, detail="该算子没有脚本内容")

    from app.services.llm import llm_manager
    from app.services.pipeline_builder import (
        _extract_python_code, _extract_main_params, _analyze_skill_calls,
        PIPELINE_BUILDER_SYSTEM_PROMPT,
    )
    from app.models.pipeline import Pipeline
    from uuid import uuid4

    await llm_manager.initialize()

    script_content = operator.script_content
    op_name = operator.name
    op_display = operator.display_name or operator.name
    op_desc = operator.description or ""

    async def generate():
        import json as json_mod
        try:
            yield f"data: {json_mod.dumps({'type': 'status', 'message': '正在分析算子脚本...'}, ensure_ascii=False)}\n\n"

            user_prompt = (
                f"请将以下算子脚本转化为一个完整的数据处理流程（Pipeline）主函数。\n\n"
                f"## 算子信息\n"
                f"- 名称: {op_display}\n"
                f"- 描述: {op_desc}\n\n"
                f"## 算子脚本\n```python\n{script_content[:8000]}\n```\n\n"
                f"请生成完整的 Python 流程主函数文件。算子中的核心处理函数请内联到主文件中（函数名加 _skill_ 前缀）。"
            )

            messages = [
                {"role": "system", "content": PIPELINE_BUILDER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]

            full_content = ""
            async for chunk in llm_manager.chat_stream_with_thinking(messages, temperature=0.2):
                event = {"type": chunk["type"], "content": chunk["content"]}
                yield f"data: {json_mod.dumps(event, ensure_ascii=False)}\n\n"
                if chunk["type"] == "content":
                    full_content += chunk["content"]

            yield f"data: {json_mod.dumps({'type': 'status', 'message': '正在解析生成代码并创建流程...'}, ensure_ascii=False)}\n\n"

            main_code = _extract_python_code(full_content)
            params = _extract_main_params(main_code)
            skill_calls = _analyze_skill_calls(main_code, str(operator_id), op_name)

            display_name = f"{op_display} - 流程"
            pipeline = Pipeline(
                id=uuid4(),
                name=f"pl_{op_name}",
                display_name=display_name,
                description=op_desc,
                main_code=main_code,
                entry_function="main",
                parameters=params,
                skill_calls=skill_calls,
                tags=operator.tags or [],
                category=operator.category,
                created_by=current_user.id,
            )
            db.add(pipeline)
            await db.flush()
            await db.refresh(pipeline)
            logger.info(f"算子转流程完成: {pipeline.display_name} ({pipeline.id})")

            yield f"data: {json_mod.dumps({'type': 'done', 'pipeline_name': display_name, 'pipeline_id': str(pipeline.id)}, ensure_ascii=False)}\n\n"

        except asyncio.CancelledError:
            yield f"data: {json_mod.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"算子转流程失败: {e}")
            yield f"data: {json_mod.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ============================================================
# 内部端点：供技能沙箱子进程调用算子（无认证，本机调用）
# ============================================================
@router.post("/internal/execute")
async def internal_execute_operator(body: dict, db: AsyncSession = Depends(get_db)):
    """内部算子执行端点（无认证，仅供技能执行器子进程本机调用）。
    根据算子名称或 ID 加载脚本并执行，返回结果。"""
    from app.models.operator import Operator
    from app.services.sandbox_ns import build_operator_namespace as _build_ns, run_async_in_thread as _run_thread
    from uuid import UUID as _UUID
    import pandas as _pd

    operator_key = body.get("operator_name") or body.get("operator_id")
    params = body.get("parameters") or {}
    user_id = body.get("user_id")
    if not operator_key:
        raise HTTPException(status_code=400, detail="operator_name 或 operator_id 必填")

    # 查找算子（按 ID 或名称）
    try:
        op_uuid = _UUID(str(operator_key))
        result = await db.execute(select(Operator).where(Operator.id == op_uuid))
    except (ValueError, TypeError):
        result = await db.execute(
            select(Operator).where(Operator.name == operator_key)
        )
    operator = result.scalar_one_or_none()
    if not operator:
        raise HTTPException(status_code=404, detail=f"算子不存在: {operator_key}")

    if not operator.script_content:
        raise HTTPException(status_code=400, detail="该算子没有可执行的脚本")

    _uid = _UUID(str(user_id)) if user_id else None

    try:
        captured = io.StringIO()
        local_ns = {"__builtins__": __builtins__, "print": lambda *a, **kw: print(*a, file=captured, **kw)}
        local_ns.update(_build_ns(_uid))

        exec(operator.script_content, local_ns)

        func = local_ns.get(operator.function_name or "")
        if not func:
            raise ValueError(f"脚本中未找到函数: {operator.function_name}")

        is_async = inspect.iscoroutinefunction(func)
        result_value = await func(**params) if is_async else func(**params)

        if hasattr(result_value, "to_dict"):
            result_value = result_value.to_dict(orient="records")

        return {"success": True, "result": result_value, "stdout": captured.getvalue() or None}
    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {str(e)}", "stdout": captured.getvalue() or None}