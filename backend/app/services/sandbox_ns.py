"""算子沙箱命名空间构建 - 供算子脚本执行时注入工具函数"""

import asyncio
import json
import threading

from pathlib import Path

from app.core.database import async_session


async def _get_allowed_paths(db, user_id) -> list[str]:
    """收集授权路径：文件链接 + 数据源目录（用户建数据源即授权）。"""
    from sqlalchemy import select as _select
    import uuid as _uuid
    # user_id 可能是 str，转为 UUID 适配数据库列类型
    if isinstance(user_id, str):
        try:
            user_id = _uuid.UUID(user_id)
        except (ValueError, AttributeError):
            pass
    allowed = []

    # 1. 文件链接
    from app.models.filelink import FileLink
    result = await db.execute(_select(FileLink).where(
        FileLink.is_active == True, FileLink.created_by == user_id
    ))
    for f in result.scalars().all():
        if f.link_type == "directory":
            allowed.append(f.path)
        else:
            allowed.append(str(Path(f.path).parent))

    # 2. 文件型数据源（csv/excel/generic_file 等）自动授权
    from app.models.datasource import DataSource
    result = await db.execute(_select(DataSource).where(
        DataSource.is_active == True, DataSource.created_by == user_id
    ))
    _FILE_DS_TYPES = {"csv", "excel", "generic_file"}
    for ds in result.scalars().all():
        if ds.type not in _FILE_DS_TYPES:
            continue
        cfg = ds.connection_config or {}
        for key in ("path", "folder_path", "file_path"):
            p = cfg.get(key)
            if p:
                allowed.append(str(Path(p).parent if Path(p).suffix else p))
        for p in cfg.get("file_paths", []):
            if p:
                allowed.append(str(Path(p).parent))

    return allowed


def run_async_in_thread(coro):
    """在独立线程的新 event loop 中运行协程，供同步算子脚本内部调用异步 DB 操作"""
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


def build_operator_namespace(current_user_id):
    """构建算子脚本执行命名空间，注入数据查询、LLM 调用等工具函数"""
    import pandas as pd

    def query_table_data(datasource_id, table_name, **kwargs):
        args = {"datasource_id": str(datasource_id), "table_name": table_name, **kwargs}

        async def _run():
            async with async_session() as db:
                from app.services.shared_tools import execute_shared_tool
                return await execute_shared_tool("query_table_data", args, db, current_user_id)

        result = json.loads(run_async_in_thread(_run()))
        if isinstance(result, dict) and "rows" in result and "columns" in result:
            return pd.DataFrame(result["rows"], columns=result["columns"])
        if isinstance(result, dict) and "error" in result:
            raise RuntimeError(result["error"])
        return result

    def get_table_schema(datasource_id, table_name):
        args = {"datasource_id": str(datasource_id), "table_name": table_name}

        async def _run():
            async with async_session() as db:
                from app.services.shared_tools import execute_shared_tool
                return await execute_shared_tool("get_table_schema", args, db, current_user_id)

        return json.loads(run_async_in_thread(_run()))

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

        result = json.loads(run_async_in_thread(_run()))
        if "error" in result:
            raise RuntimeError(result["error"])
        return result["id"]

    def llm_chat(prompt, system_prompt=None, temperature=0.7, max_tokens=2000):
        """在算子脚本中直接调用大模型（自动使用当前用户的 LLM 配置）"""
        from app.services.llm import llm_manager, init_user_llm_context, reset_user_llm_config

        async def _run():
            if current_user_id:
                await init_user_llm_context(current_user_id)
            try:
                await llm_manager.initialize()
                if system_prompt:
                    messages = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ]
                    return await llm_manager.chat_with_messages(
                        messages, temperature=temperature, max_tokens=max_tokens
                    )
                return await llm_manager.chat(
                    prompt, temperature=temperature, max_tokens=max_tokens
                )
            except Exception as e:
                raise RuntimeError(f"平台限制：llm_chat 调用失败 — {e}") from e
            finally:
                reset_user_llm_config()

        return run_async_in_thread(_run())

    def execute_sql(datasource_id, sql, params=None, limit=10000):
        """在数据源上执行 SQL，返回 DataFrame（支持 JOIN/聚合/窗口函数）"""
        import uuid as _uuid

        async def _run():
            async with async_session() as db:
                from sqlalchemy import select as _select
                from app.models.datasource import DataSource as _DS
                from app.services.connectors import get_connector
                result = await db.execute(_select(_DS).where(_DS.id == _uuid.UUID(str(datasource_id))))
                ds = result.scalar_one_or_none()
                if not ds:
                    raise RuntimeError(f"数据源不存在: {datasource_id}")
                connector = get_connector(ds.type, ds.connection_config or {})
                try:
                    await connector.connect()
                    df = await connector.execute_query(sql)
                finally:
                    await connector.close()
                if df is not None and not df.empty and len(df) > limit:
                    df = df.head(limit)
                return df

        return run_async_in_thread(_run())

    def list_tables(datasource_id):
        """列出数据源中的所有表名，返回 list[str]"""
        import uuid as _uuid

        async def _run():
            async with async_session() as db:
                from sqlalchemy import select as _select
                from app.models.datasource import DataSource as _DS
                from app.services.connectors import get_connector
                result = await db.execute(_select(_DS).where(_DS.id == _uuid.UUID(str(datasource_id))))
                ds = result.scalar_one_or_none()
                if not ds:
                    raise RuntimeError(f"数据源不存在: {datasource_id}")
                connector = get_connector(ds.type, ds.connection_config or {})
                try:
                    await connector.connect()
                    schema = await connector.get_schema()
                finally:
                    await connector.close()
                return [t.get("table_name", str(t)) if isinstance(t, dict) else str(t) for t in schema]

        return run_async_in_thread(_run())

    def iter_table_data(datasource_id, table_name, chunk_size=10000):
        """分块迭代读取大表数据，返回生成器，每次 yield DataFrame"""
        import uuid as _uuid

        def _generator():
            page = 1
            while True:
                async def _fetch(p=page):
                    async with async_session() as db:
                        from sqlalchemy import select as _select
                        from app.models.datasource import DataSource as _DS
                        from app.services.connectors import get_connector
                        result = await db.execute(_select(_DS).where(_DS.id == _uuid.UUID(str(datasource_id))))
                        ds = result.scalar_one_or_none()
                        if not ds:
                            raise RuntimeError(f"数据源不存在: {datasource_id}")
                        connector = get_connector(ds.type, ds.connection_config or {})
                        try:
                            await connector.connect()
                            df = await connector.get_table_data(table_name, page=p, page_size=chunk_size)
                            stats = await connector.get_table_stats(table_name)
                        finally:
                            await connector.close()
                        return df, stats.get("row_count", len(df))

                df, total = run_async_in_thread(_fetch())
                if df is None or df.empty:
                    break
                yield df
                if page * chunk_size >= total:
                    break
                page += 1

        return _generator()

    def read_file(path, format=None):
        """读取文件（自动检测格式，路径须在文件链接授权目录内）"""
        from pathlib import Path

        async def _run():
            async with async_session() as db:
                allowed = await _get_allowed_paths(db, current_user_id)

                resolved = Path(path).resolve()
                ok = any(str(resolved).startswith(str(Path(a).resolve())) for a in allowed)
                if not ok:
                    raise RuntimeError(f"路径不在授权目录范围内: {path}")

                if not resolved.exists():
                    raise RuntimeError(f"文件不存在: {path}")

                ext = resolved.suffix.lower()
                if ext == ".json":
                    return json.loads(resolved.read_text(encoding="utf-8"))
                elif ext == ".csv":
                    return pd.read_csv(resolved)
                elif ext in (".xlsx", ".xls"):
                    return pd.read_excel(resolved)
                elif ext == ".parquet":
                    return pd.read_parquet(resolved)
                elif ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tiff", ".tif"):
                    # 图片 fail-fast：绝不返回 UTF-8 乱码（会掩盖错误信号，诱导把乱码当数据传给 llm_vision）
                    raise RuntimeError(f"read_file 不支持读取图片文件({ext})。请直接将图片路径传给 llm_vision(image_path, prompt) 进行 OCR/识别。")
                elif ext in (".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm", ".m4v", ".mpg", ".mpeg", ".ts", ".3gp"):
                    raise RuntimeError(f"read_file 不支持读取视频文件({ext})。请使用 extract_video_info(video_path) 提取视频信息，或 extract_keyframes(video_path) 抽取关键帧。")
                else:
                    return resolved.read_text(encoding="utf-8")

        return run_async_in_thread(_run())

    def write_file(path, data, format=None):
        """写入文件（路径须在文件链接授权目录内）"""
        from pathlib import Path

        async def _run():
            async with async_session() as db:
                allowed = await _get_allowed_paths(db, current_user_id)

                resolved = Path(path).resolve()
                ok = any(str(resolved).startswith(str(Path(a).resolve())) for a in allowed)
                if not ok:
                    raise RuntimeError(f"路径不在授权目录范围内: {path}")

                resolved.parent.mkdir(parents=True, exist_ok=True)
                ext = resolved.suffix.lower()
                if ext == ".json" or format == "json":
                    resolved.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                elif ext == ".csv" or format == "csv":
                    if hasattr(data, "to_csv"):
                        data.to_csv(resolved, index=False, encoding="utf-8-sig")
                    elif isinstance(data, list) and data and isinstance(data[0], dict):
                        pd.DataFrame(data).to_csv(resolved, index=False, encoding="utf-8-sig")
                    else:
                        resolved.write_text(str(data), encoding="utf-8")
                else:
                    if isinstance(data, (dict, list)):
                        resolved.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                    else:
                        resolved.write_text(str(data), encoding="utf-8")
                return {"success": True, "path": str(resolved), "size": resolved.stat().st_size}

        return run_async_in_thread(_run())

    def compute_map(fn, partitions, backend="local", **kwargs):
        """对分块数据并行执行函数（分布式计算抽象）
        backend: "sequential" / "local"(multiprocessing) / "ray"(预留)
        """
        from app.services.compute_backend import compute_map as _cm
        return _cm(fn, partitions, backend=backend, **kwargs)

    def llm_vision(image_path, prompt, system_prompt=None, temperature=0.3, max_tokens=2000):
        """图片理解/OCR（发送图片到视觉大模型，返回文本）"""
        import base64 as _b64
        from pathlib import Path

        async def _run():
            async with async_session() as db:
                allowed = await _get_allowed_paths(db, current_user_id)

                resolved = Path(image_path).resolve()
                ok = any(str(resolved).startswith(str(Path(a).resolve())) for a in allowed)
                if not ok:
                    raise RuntimeError(f"路径不在授权目录范围内: {image_path}")
                if not resolved.exists():
                    raise RuntimeError(f"图片文件不存在: {image_path}")

                ext = resolved.suffix.lower()
                mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                            ".bmp": "image/bmp", ".webp": "image/webp", ".gif": "image/gif", ".tiff": "image/tiff"}
                mime = mime_map.get(ext, "image/jpeg")

                # 图片压缩：缩到最大宽度 1024px，OCR 不需要原始分辨率，省 60-70% token
                raw_bytes = resolved.read_bytes()
                try:
                    import io as _io
                    from PIL import Image as _PILImage
                    img = _PILImage.open(_io.BytesIO(raw_bytes))
                    if img.width > 1024 or img.height > 1024:
                        ratio = min(1024 / img.width, 1024 / img.height)
                        new_size = (int(img.width * ratio), int(img.height * ratio))
                        img = img.resize(new_size, _PILImage.LANCZOS)
                    buf = _io.BytesIO()
                    # 统一转 JPEG 压缩（质量 85，文件小且 OCR 效果不受影响）
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")
                    img.save(buf, format="JPEG", quality=85)
                    image_data = _b64.b64encode(buf.getvalue()).decode("utf-8")
                    mime = "image/jpeg"  # 压缩后统一为 JPEG
                except Exception:
                    # PIL 不可用时回退到原始图片
                    image_data = _b64.b64encode(raw_bytes).decode("utf-8")

                from app.services.llm import llm_manager, init_user_llm_context, reset_user_llm_config
                if current_user_id:
                    await init_user_llm_context(current_user_id)
                try:
                    await llm_manager.initialize()
                    messages = []
                    if system_prompt:
                        messages.append({"role": "system", "content": system_prompt})
                    messages.append({
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_data}"}},
                            {"type": "text", "text": prompt},
                        ],
                    })
                    # 视觉模型：按 provider 自动选择，不支持则报环境错误
                    _vision_model = llm_manager._eff_vision_model()
                    if not _vision_model:
                        raise RuntimeError(f"Provider {llm_manager.provider} 不支持视觉模型，无法处理图片识别任务")
                    resp = await llm_manager._client.chat.completions.create(
                        model=_vision_model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    return resp.choices[0].message.content
                except Exception as e:
                    raise RuntimeError(f"平台限制：llm_vision 调用失败 — {e}") from e
                finally:
                    reset_user_llm_config()

        return run_async_in_thread(_run())

    def extract_video_info(video_path):
        """提取视频元数据（时长、分辨率、帧率、编码等）"""
        from pathlib import Path
        from app.services.video_utils import probe_video, is_video_file

        async def _run():
            async with async_session() as db:
                allowed = await _get_allowed_paths(db, current_user_id)
                resolved = Path(video_path).resolve()
                ok = any(str(resolved).startswith(str(Path(a).resolve())) for a in allowed)
                if not ok:
                    raise RuntimeError(f"路径不在授权目录范围内: {video_path}")
                if not resolved.exists():
                    raise RuntimeError(f"视频文件不存在: {video_path}")
                if not is_video_file(str(resolved)):
                    raise RuntimeError(f"不支持的视频格式: {resolved.suffix}")
                return probe_video(str(resolved))

        return run_async_in_thread(_run())

    def extract_keyframes(video_path, max_frames=8, output_dir=None, method="auto"):
        """抽取视频关键帧，输出为 JPEG 图片文件"""
        from pathlib import Path
        from app.services.video_utils import extract_keyframes as _extract, is_video_file

        async def _run():
            async with async_session() as db:
                allowed = await _get_allowed_paths(db, current_user_id)
                resolved = Path(video_path).resolve()
                ok = any(str(resolved).startswith(str(Path(a).resolve())) for a in allowed)
                if not ok:
                    raise RuntimeError(f"路径不在授权目录范围内: {video_path}")
                if not resolved.exists():
                    raise RuntimeError(f"视频文件不存在: {video_path}")
                if not is_video_file(str(resolved)):
                    raise RuntimeError(f"不支持的视频格式: {resolved.suffix}")
                if output_dir:
                    out = Path(output_dir).resolve()
                    ok2 = any(str(out).startswith(str(Path(a).resolve())) for a in allowed)
                    if not ok2:
                        raise RuntimeError(f"output_dir 不在授权目录范围内: {output_dir}")
                return _extract(str(resolved), max_frames=max_frames, output_dir=output_dir, method=method)

        return run_async_in_thread(_run())

    def call_operator(operator_name, **params):
        """调用用户自定义算子（通过内部 HTTP 端点执行算子脚本）"""
        import urllib.request as _ureq

        async def _run():
            from app.core.database import async_session
            from sqlalchemy import select as _sel
            from app.models.operator import Operator
            from uuid import UUID as _UUID
            import inspect as _inspect
            import io as _io

            # 查找算子（按 ID 或名称）
            try:
                op_id = _UUID(str(operator_name))
                r = await async_session().execute(_sel(Operator).where(Operator.id == op_id))
            except (ValueError, TypeError):
                async with async_session() as _db:
                    r = await _db.execute(_sel(Operator).where(Operator.name == operator_name))
            op = r.scalar_one_or_none()
            if not op:
                raise RuntimeError(f"算子不存在: {operator_name}")
            if not op.script_content:
                raise RuntimeError(f"算子 '{operator_name}' 没有可执行脚本")

            captured = _io.StringIO()
            ns = {"__builtins__": __builtins__, "print": lambda *a, **kw: print(*a, file=captured, **kw)}
            ns.update(build_operator_namespace(current_user_id))
            exec(op.script_content, ns)
            func = ns.get(op.function_name or "")
            if not func:
                raise RuntimeError(f"算子脚本中未找到函数: {op.function_name}")

            is_async = _inspect.iscoroutinefunction(func)
            result = await func(**params) if is_async else func(**params)
            if hasattr(result, "to_dict"):
                result = result.to_dict(orient="records")
            return {"success": True, "result": result, "stdout": captured.getvalue() or None}

        try:
            return run_async_in_thread(_run())
        except Exception as e:
            return {"success": False, "error": f"{type(e).__name__}: {str(e)}"}

    return {
        "query_table_data": query_table_data,
        "get_table_schema": get_table_schema,
        "get_datasource_id_by_name": get_datasource_id_by_name,
        "llm_chat": llm_chat,
        "llm_vision": llm_vision,
        "extract_video_info": extract_video_info,
        "extract_keyframes": extract_keyframes,
        "execute_sql": execute_sql,
        "list_tables": list_tables,
        "iter_table_data": iter_table_data,
        "read_file": read_file,
        "write_file": write_file,
        "compute_map": compute_map,
        "call_operator": call_operator,
        "pd": pd,
        "json": json,
    }
