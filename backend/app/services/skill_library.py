"""技能库服务 - 向量搜索和技能匹配"""

import numpy as np
from typing import List, Dict, Any, Optional
from loguru import logger
from app.services.llm import llm_manager


class VectorIndex:
    """向量索引 - 用于快速相似度搜索"""

    def __init__(self, dimension: int = 1536):
        self.dimension = dimension
        self.vectors: List[np.ndarray] = []
        self.ids: List[str] = []
        self.metadata: List[Dict[str, Any]] = []

    def add(self, vector: List[float], id: str, metadata: Dict[str, Any] = None):
        """添加向量到索引"""
        vec = np.array(vector, dtype=np.float32)
        # 归一化向量
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm

        self.vectors.append(vec)
        self.ids.append(id)
        self.metadata.append(metadata or {})

    def search(self, query_vector: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        """搜索最相似的向量"""
        if not self.vectors:
            return []

        query = np.array(query_vector, dtype=np.float32)
        # 归一化查询向量
        norm = np.linalg.norm(query)
        if norm > 0:
            query = query / norm

        # 计算余弦相似度
        similarities = [np.dot(query, vec) for vec in self.vectors]

        # 获取top_k个最相似的索引
        top_indices = np.argsort(similarities)[::-1][:top_k]

        results = []
        for idx in top_indices:
            results.append({
                "id": self.ids[idx],
                "score": float(similarities[idx]),
                "metadata": self.metadata[idx],
            })

        return results

    def remove(self, id: str):
        """移除向量"""
        if id in self.ids:
            idx = self.ids.index(id)
            self.vectors.pop(idx)
            self.ids.pop(idx)
            self.metadata.pop(idx)

    def clear(self):
        """清空索引"""
        self.vectors.clear()
        self.ids.clear()
        self.metadata.clear()


class SkillLibrary:
    """技能库 - 管理技能和向量搜索"""

    def __init__(self):
        self.vector_index = VectorIndex()
        self.skills: Dict[str, Dict[str, Any]] = {}
        self._initialized = False

    async def initialize(self):
        """初始化技能库"""
        if self._initialized:
            return

        # TODO: 从数据库加载所有技能并构建向量索引
        # 这里先创建一些内置技能示例
        await self._load_builtin_skills()

        self._initialized = True
        logger.info(f"技能库初始化完成,共{len(self.skills)}个技能")

    async def _load_builtin_skills(self):
        """加载内置技能"""
        builtin_skills = [
            {
                "id": "skill_select",
                "name": "select",
                "display_name": "列选择",
                "description": "选择数据中的特定列",
                "category": "transform",
                "tags": ["数据选择", "列操作", "基础算子"],
                "usage_examples": [
                    "选择用户表中的姓名和年龄列",
                    "从订单数据中提取订单号和金额",
                    "筛选出销售数据中的商品名称和销量",
                ],
                "parameters": {
                    "columns": {
                        "type": "list",
                        "description": "要选择的列名列表",
                        "required": True,
                    }
                },
                "json_example": '{"columns": ["姓名", "年龄"]}',
            },
            {
                "id": "skill_filter",
                "name": "filter",
                "display_name": "数据过滤",
                "description": "根据条件过滤数据行",
                "category": "filter",
                "tags": ["数据过滤", "条件筛选", "基础算子"],
                "usage_examples": [
                    "筛选出年龄大于18岁的用户",
                    "过滤销售额超过10000的订单",
                    "选择状态为完成的任务",
                ],
                "parameters": {
                    "condition": {
                        "type": "str",
                        "description": "过滤条件表达式",
                        "required": True,
                    }
                },
                "json_example": '{"condition": "年龄 > 18"}',
            },
            {
                "id": "skill_groupby",
                "name": "groupby",
                "display_name": "分组聚合",
                "description": "按列分组并进行聚合计算",
                "category": "aggregate",
                "tags": ["数据聚合", "分组统计", "基础算子"],
                "usage_examples": [
                    "按地区统计销售额总和",
                    "按用户分组计算平均购买金额",
                    "按产品类别统计销售数量",
                ],
                "parameters": {
                    "group_column": {
                        "type": "str",
                        "description": "分组列名",
                        "required": True,
                    },
                    "agg_column": {
                        "type": "str",
                        "description": "聚合列名",
                        "required": True,
                    },
                    "agg_func": {
                        "type": "str",
                        "description": "聚合函数(sum, mean, count, max, min)",
                        "required": True,
                        "default": "sum",
                    }
                },
                "json_example": '{"group_column": "地区", "agg_column": "销售额", "agg_func": "sum"}',
            },
            {
                "id": "skill_sort",
                "name": "sort",
                "display_name": "数据排序",
                "description": "按指定列排序数据",
                "category": "transform",
                "tags": ["数据排序", "基础算子"],
                "usage_examples": [
                    "按销售额降序排列",
                    "按创建时间升序排序",
                    "按用户年龄从小到大排序",
                ],
                "parameters": {
                    "column": {
                        "type": "str",
                        "description": "排序列名",
                        "required": True,
                    },
                    "ascending": {
                        "type": "bool",
                        "description": "是否升序",
                        "required": False,
                        "default": True,
                    }
                },
                "json_example": '{"column": "销售额", "ascending": false}',
            },
            {
                "id": "skill_dropna",
                "name": "dropna",
                "display_name": "删除空值",
                "description": "删除包含空值的行",
                "category": "cleaning",
                "tags": ["数据清洗", "空值处理", "基础算子"],
                "usage_examples": [
                    "删除包含空值的行",
                    "移除缺失数据",
                    "清理不完整记录",
                ],
                "parameters": {
                    "columns": {
                        "type": "list",
                        "description": "要检查的列名列表,为空则检查所有列",
                        "required": False,
                    }
                },
                "json_example": '{"columns": ["姓名", "年龄"]}',
            },
            {
                "id": "skill_fillna",
                "name": "fillna",
                "display_name": "填充空值",
                "description": "填充空值",
                "category": "cleaning",
                "tags": ["数据清洗", "空值处理", "基础算子"],
                "usage_examples": [
                    "用0填充空值",
                    "用平均值填充缺失值",
                    "用前一个值填充空值",
                ],
                "parameters": {
                    "value": {
                        "type": "any",
                        "description": "填充值",
                        "required": False,
                    },
                    "method": {
                        "type": "str",
                        "description": "填充方法(ffill, bfill, mean, median)",
                        "required": False,
                    }
                },
                "json_example": '{"value": 0}',
            },
            {
                "id": "skill_aggregate",
                "name": "aggregate",
                "display_name": "聚合统计",
                "description": "对列进行聚合计算，如求和、均值、最大值等",
                "category": "aggregate",
                "tags": ["数据聚合", "统计", "基础算子"],
                "usage_examples": [
                    "计算每列的平均值",
                    "求销售额总和和订单数量",
                ],
                "parameters": {
                    "functions": {
                        "type": "dict",
                        "description": "列到聚合函数的映射，如 {\"销售额\": \"sum\", \"数量\": \"mean\"}",
                        "required": True,
                    }
                },
                "json_example": '{"functions": {"销售额": "sum", "数量": "mean"}}',
            },
            {
                "id": "skill_join",
                "name": "join",
                "display_name": "数据连接",
                "description": "将两个数据表按指定键连接",
                "category": "transform",
                "tags": ["数据连接", "合并", "基础算子"],
                "usage_examples": [
                    "按用户ID连接订单表和用户表",
                    "内连接两个数据源",
                ],
                "parameters": {
                    "on": {
                        "type": "list",
                        "description": "连接键列名列表",
                        "required": True,
                    },
                    "how": {
                        "type": "str",
                        "description": "连接方式: inner, left, right, outer",
                        "required": False,
                        "default": "inner",
                    }
                },
                "json_example": '{"on": ["用户ID"], "how": "inner"}',
            },
            {
                "id": "skill_rename",
                "name": "rename",
                "display_name": "列重命名",
                "description": "重命名数据列",
                "category": "transform",
                "tags": ["列操作", "重命名", "基础算子"],
                "usage_examples": [
                    "把name列改名为姓名",
                    "重命名多个列",
                ],
                "parameters": {
                    "mapping": {
                        "type": "dict",
                        "description": "旧列名到新列名的映射",
                        "required": True,
                    }
                },
                "json_example": '{"mapping": {"name": "姓名", "age": "年龄"}}',
            },
            {
                "id": "skill_statistics",
                "name": "statistics",
                "display_name": "统计描述",
                "description": "生成数据的统计描述信息（均值、标准差、最值等）",
                "category": "analysis",
                "tags": ["数据分析", "统计", "基础算子"],
                "usage_examples": [
                    "查看数据的统计信息",
                    "生成描述性统计报告",
                ],
                "parameters": {},
                "json_example": '{}',
            },
        ]

        # 添加内置技能到技能库
        for skill in builtin_skills:
            await self.register_skill(skill)

    async def register_skill(self, skill: Dict[str, Any]):
        """注册技能"""
        skill_id = skill.get("id")
        if not skill_id:
            logger.error("技能缺少ID")
            return

        # 存储技能
        self.skills[skill_id] = skill

        # 尝试生成向量（如果LLM可用）
        try:
            # 组合技能描述和使用示例
            text = skill.get("description", "")
            examples = skill.get("usage_examples", [])
            if examples:
                text += " " + " ".join(examples)

            # 生成向量
            vector = await llm_manager.embed(text)

            # 添加到向量索引
            self.vector_index.add(
                vector=vector,
                id=skill_id,
                metadata={
                    "name": skill.get("name"),
                    "display_name": skill.get("display_name"),
                    "category": skill.get("category"),
                    "tags": skill.get("tags", []),
                }
            )

            logger.debug(f"技能注册成功: {skill_id}")

        except Exception as e:
            # 向量化失败时，仍然保留技能，使用关键词匹配
            logger.warning(f"技能向量化失败 {skill_id}，将使用关键词匹配: {e}")
            self.skills[skill_id] = skill  # 确保技能已存储

    async def search_similar(
        self,
        query: str,
        top_k: int = 5,
        filters: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """搜索相似技能"""
        if not self._initialized:
            await self.initialize()

        # 尝试向量搜索
        try:
            query_vector = await llm_manager.embed(query)
            results = self.vector_index.search(query_vector, top_k=top_k * 2)

            # 应用过滤器
            if filters:
                filtered_results = []
                for result in results:
                    skill = self.skills.get(result["id"])
                    if skill and self._match_filters(skill, filters):
                        filtered_results.append(result)
                results = filtered_results[:top_k]

            # 补充完整的技能信息
            for result in results:
                skill = self.skills.get(result["id"])
                if skill:
                    result["skill"] = skill

            if results:
                return results[:top_k]

        except Exception as e:
            logger.warning(f"向量搜索失败，使用关键词匹配: {e}")

        # 回退到关键词匹配
        return self._keyword_search(query, top_k, filters)

    def _keyword_search(
        self,
        query: str,
        top_k: int = 5,
        filters: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """关键词匹配搜索"""
        query_lower = query.lower()
        results = []

        for skill_id, skill in self.skills.items():
            # 计算关键词匹配分数
            score = 0.0

            # 检查技能名称
            if skill.get("name") and skill.get("name").lower() in query_lower:
                score += 0.5

            # 检查显示名称
            if skill.get("display_name") and skill.get("display_name").lower() in query_lower:
                score += 0.3

            # 检查描述关键词
            desc = skill.get("description", "").lower()
            for word in query_lower.split():
                if word in desc:
                    score += 0.1

            # 检查使用示例
            examples = skill.get("usage_examples", [])
            for example in examples:
                if example.lower() in query_lower:
                    score += 0.2

            # 检查标签
            tags = skill.get("tags", [])
            for tag in tags:
                if tag.lower() in query_lower:
                    score += 0.15

            # 检查分类
            category = skill.get("category", "")
            if category and category.lower() in query_lower:
                score += 0.1

            # 应用过滤器
            if filters and not self._match_filters(skill, filters):
                continue

            if score > 0:
                results.append({
                    "id": skill_id,
                    "score": score,
                    "skill": skill
                })

        # 按分数排序
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def _match_filters(self, skill: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        """检查技能是否匹配过滤器"""
        for key, value in filters.items():
            if key == "category":
                if skill.get("category") != value:
                    return False
            elif key == "tags":
                skill_tags = skill.get("tags", [])
                if not any(tag in skill_tags for tag in value):
                    return False
        return True

    def get_skill(self, skill_id: str) -> Optional[Dict[str, Any]]:
        """获取技能"""
        return self.skills.get(skill_id)

    def list_skills(
        self,
        category: str = None,
        tags: List[str] = None
    ) -> List[Dict[str, Any]]:
        """列出技能"""
        skills = list(self.skills.values())

        if category:
            skills = [s for s in skills if s.get("category") == category]

        if tags:
            skills = [s for s in skills if any(tag in s.get("tags", []) for tag in tags)]

        return skills


# 全局技能库实例
skill_library = SkillLibrary()
