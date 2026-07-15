"""计算后端抽象层 — 分离"算什么"和"在哪里算"

用法:
    from app.services.compute_backend import compute_map

    # 用户脚本代码不变，只换 backend 参数
    results = compute_map(chunks, clean_fn, backend="local")     # 单机 multiprocessing
    results = compute_map(chunks, clean_fn, backend="ray")       # RAY 分布式（未来）

设计原则:
  1. 函数可序列化 — fn 必须是顶层函数或 pickle 可序列化的对象
  2. 数据可分块 — partitions 是独立的工作单元（配合 iter_table_data 使用）
  3. 后端可插拔 — 新增后端只需实现 ComputeBackend 接口，注册到 _BACKENDS

预留扩展:
  - backend="ray": 需要 ray 已安装，序列化 fn + partitions 分发到 worker
  - backend="dask": 需要 dask 已安装，使用 delayed API
"""

from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Type

from loguru import logger


class ComputeBackend(ABC):
    """计算后端抽象基类"""

    name: str = "base"

    @abstractmethod
    def map(self, fn: Callable, partitions: List[Any], **kwargs) -> List[Any]:
        """对每个分块执行 fn，返回结果列表（顺序与 partitions 一致）"""
        ...

    def reduce(self, fn: Callable, partitions: List[Any], **kwargs) -> Any:
        """先 map 再归约：map(fn, partitions) → fn(results)"""
        mapped = self.map(fn, partitions, **kwargs)
        return fn(mapped)


class SequentialBackend(ComputeBackend):
    """顺序执行后端（调试用，无并行）"""

    name = "sequential"

    def map(self, fn: Callable, partitions: List[Any], **kwargs) -> List[Any]:
        return [fn(p) for p in partitions]


class LocalBackend(ComputeBackend):
    """本机并行后端（multiprocessing.Pool）"""

    name = "local"

    def map(self, fn: Callable, partitions: List[Any], **kwargs) -> List[Any]:
        workers = kwargs.get("workers")
        if workers is None:
            import os
            workers = min(len(partitions), os.cpu_count() or 4)
        if workers <= 1 or len(partitions) <= 1:
            return [fn(p) for p in partitions]

        try:
            from multiprocessing import Pool
            with Pool(processes=workers) as pool:
                return pool.map(fn, partitions)
        except Exception as e:
            logger.warning(f"multiprocessing 失败，降级为顺序执行: {e}")
            return [fn(p) for p in partitions]


class RayBackend(ComputeBackend):
    """RAY 分布式后端（需安装 ray，当前为预留占位）

    启用条件: settings.COMPUTE_BACKEND == "ray" 且 ray 已安装
    工作方式:
      1. ray.init() 连接集群
      2. @ray.remote(fn) 序列化函数
      3. ray.get([fn.remote(p) for p in partitions]) 并行执行
      4. 返回结果列表
    """

    name = "ray"
    _initialized = False

    def _ensure_init(self):
        if not self._initialized:
            try:
                ray = importlib.import_module("ray")
                ray.init(ignore_reinit_error=True)
                RayBackend._initialized = True
                logger.info("RAY 后端已初始化")
            except ImportError:
                raise RuntimeError("RAY 后端需要安装 ray: pip install ray")

    def map(self, fn: Callable, partitions: List[Any], **kwargs) -> List[Any]:
        self._ensure_init()
        ray = importlib.import_module("ray")

        @ray.remote
        def _remote(fn, partition):
            return fn(partition)

        futures = [_remote.remote(fn, p) for p in partitions]
        return ray.get(futures)


# ==================== 后端注册表 ====================

_BACKENDS: Dict[str, ComputeBackend] = {
    "sequential": SequentialBackend(),
    "local": LocalBackend(),
    "ray": RayBackend(),
}


def register_backend(name: str, backend: ComputeBackend) -> None:
    """注册自定义计算后端"""
    _BACKENDS[name] = backend
    logger.info(f"计算后端已注册: {name}")


def get_backend(name: str = "local") -> ComputeBackend:
    """获取计算后端实例"""
    backend = _BACKENDS.get(name)
    if backend is None:
        logger.warning(f"未知计算后端 '{name}'，降级为 local")
        return _BACKENDS["local"]
    return backend


def list_backends() -> List[str]:
    """列出所有已注册的后端名"""
    return list(_BACKENDS.keys())


# ==================== 公共 API ====================

def compute_map(
    fn: Callable,
    partitions: List[Any],
    backend: str = "local",
    **kwargs,
) -> List[Any]:
    """对分块数据并行执行函数（核心 API）

    参数:
        fn: 处理函数，接收一个 partition（DataFrame/list/dict），返回处理结果
        partitions: 分块列表，通常来自 iter_table_data
        backend: 计算后端 — "sequential"(顺序调试) / "local"(本机并行) / "ray"(分布式)
        **kwargs: 传递给后端的额外参数（如 workers=4）

    返回:
        结果列表，顺序与 partitions 一致

    示例:
        chunks = list(iter_table_data(ds_id, "big_table", chunk_size=50000))

        def clean(df):
            return df.dropna().reset_index(drop=True)

        results = compute_map(clean, chunks, backend="local", workers=4)
        final = pd.concat(results, ignore_index=True)
    """
    if not partitions:
        return []

    b = get_backend(backend)
    logger.info(f"compute_map: backend={b.name}, partitions={len(partitions)}")
    return b.map(fn, partitions, **kwargs)


def compute_reduce(
    fn: Callable,
    partitions: List[Any],
    backend: str = "local",
    **kwargs,
) -> Any:
    """先 map 再 reduce：对每个分块执行 fn，然后对结果再执行一次 fn 归约"""
    if not partitions:
        return None

    b = get_backend(backend)
    return b.reduce(fn, partitions, **kwargs)
