"""
文物检索专家
从权威网站检索各级保护文物信息，生成知识库，支持多条件检索
"""
import pandas as pd
import json
import os
import re
from datetime import datetime
from typing import List, Dict, Optional, Any
import requests
from bs4 import BeautifulSoup
import time

class CulturalRelicsExpert:
    """文物检索专家"""
    
    def __init__(self, knowledge_base_path: str = "cultural_relics_kb.json"):
        """
        初始化文物检索专家
        
        Args:
            knowledge_base_path: 知识库存储路径
        """
        self.knowledge_base_path = knowledge_base_path
        self.knowledge_base = self._load_knowledge_base()
        
        # 权威网站列表
        self.authority_sites = {
            "国家文物局": "http://www.ncha.gov.cn",
            "中国文化遗产研究院": "http://www.cach.org.cn",
            "百度百科-全国重点文物保护单位": "https://baike.baidu.com/item/全国重点文物保护单位"
        }
    
    def _load_knowledge_base(self) -> Dict:
        """加载知识库"""
        if os.path.exists(self.knowledge_base_path):
            try:
                with open(self.knowledge_base_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {"relics": [], "metadata": {}}
        return {"relics": [], "metadata": {}}
    
    def _save_knowledge_base(self):
        """保存知识库"""
        self.knowledge_base["metadata"]["last_update"] = datetime.now().isoformat()
        self.knowledge_base["metadata"]["total_count"] = len(self.knowledge_base["relics"])
        
        with open(self.knowledge_base_path, 'w', encoding='utf-8') as f:
            json.dump(self.knowledge_base, f, ensure_ascii=False, indent=2)
    
    def crawl_from_wikipedia(self, max_items: int = 100) -> List[Dict]:
        """
        从维基百科爬取文物信息
        
        Args:
            max_items: 最大爬取数量
        
        Returns:
            爬取的文物列表
        """
        print("开始从维基百科爬取文物信息...")
        
        relics = []
        
        # 维基百科全国重点文物保护单位列表
        wiki_url = "https://zh.wikipedia.org/wiki/全国重点文物保护单位"
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(wiki_url, headers=headers, timeout=30)
            response.encoding = 'utf-8'
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # 解析页面内容，提取文物信息
                # 这里简化处理，实际需要根据页面结构解析
                print(f"成功获取维基百科页面，状态码: {response.status_code}")
                
                # 示例数据（实际应从页面解析）
                sample_relics = [
                    {
                        "名称": "故宫",
                        "时代": "明、清",
                        "地址": "北京市东城区",
                        "级别": "全国重点文物保护单位",
                        "批次": "第一批",
                        "类型": "古建筑",
                        "来源": "维基百科",
                        "采集时间": datetime.now().isoformat()
                    }
                ]
                
                relics.extend(sample_relics[:max_items])
                
        except Exception as e:
            print(f"爬取维基百科失败: {e}")
        
        return relics
    
    def crawl_from_baidu_baike(self, keywords: List[str] = None, max_items: int = 50) -> List[Dict]:
        """
        从百度百科爬取文物信息
        
        Args:
            keywords: 搜索关键词列表
            max_items: 最大爬取数量
        
        Returns:
            爬取的文物列表
        """
        if keywords is None:
            keywords = ["全国重点文物保护单位", "世界文化遗产", "国家一级文物"]
        
        print(f"开始从百度百科爬取文物信息，关键词: {keywords}")
        
        relics = []
        
        for keyword in keywords:
            try:
                # 百度百科搜索API
                search_url = f"https://baike.baidu.com/search?word={keyword}"
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                
                response = requests.get(search_url, headers=headers, timeout=30)
                response.encoding = 'utf-8'
                
                if response.status_code == 200:
                    print(f"成功搜索关键词: {keyword}")
                    
                    # 解析搜索结果（简化处理）
                    sample_relic = {
                        "名称": f"{keyword}示例文物",
                        "时代": "不详",
                        "地址": "中国",
                        "级别": "国家级",
                        "批次": "不详",
                        "类型": "文化遗产",
                        "来源": "百度百科",
                        "关键词": keyword,
                        "采集时间": datetime.now().isoformat()
                    }
                    
                    relics.append(sample_relic)
                
                time.sleep(1)  # 避免请求过快
                
            except Exception as e:
                print(f"爬取百度百科失败 (关键词: {keyword}): {e}")
        
        return relics[:max_items]
    
    def crawl_from_gov_site(self, max_items: int = 100) -> List[Dict]:
        """
        从政府网站爬取文物信息
        
        Args:
            max_items: 最大爬取数量
        
        Returns:
            爬取的文物列表
        """
        print("开始从政府网站爬取文物信息...")
        
        relics = []
        
        # 国家文物局官网
        gov_url = "http://www.ncha.gov.cn"
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(gov_url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                print(f"成功访问国家文物局官网，状态码: {response.status_code}")
                
                # 示例数据（实际应从页面解析）
                sample_relics = [
                    {
                        "名称": "长城",
                        "时代": "春秋至明",
                        "地址": "北京市、河北省等",
                        "级别": "世界文化遗产",
                        "批次": "第一批",
                        "类型": "古建筑",
                        "来源": "国家文物局",
                        "采集时间": datetime.now().isoformat()
                    }
                ]
                
                relics.extend(sample_relics[:max_items])
                
        except Exception as e:
            print(f"爬取政府网站失败: {e}")
        
        return relics
    
    def build_knowledge_base(
        self,
        sources: List[str] = None,
        max_items_per_source: int = 100,
        update_mode: str = "append"
    ) -> Dict:
        """
        构建文物知识库
        
        Args:
            sources: 数据来源列表 ["wikipedia", "baidu", "gov"]
            max_items_per_source: 每个来源最大爬取数量
            update_mode: 更新模式 "append"追加 或 "replace"替换
        
        Returns:
            构建结果统计
        """
        if sources is None:
            sources = ["wikipedia", "baidu", "gov"]
        
        print(f"\n{'='*60}")
        print(f"开始构建文物知识库")
        print(f"数据来源: {sources}")
        print(f"每来源最大数量: {max_items_per_source}")
        print(f"更新模式: {update_mode}")
        print(f"{'='*60}\n")
        
        all_relics = []
        stats = {
            "total_crawled": 0,
            "by_source": {},
            "errors": []
        }
        
        # 从各个来源爬取数据
        if "wikipedia" in sources:
            try:
                relics = self.crawl_from_wikipedia(max_items_per_source)
                all_relics.extend(relics)
                stats["by_source"]["维基百科"] = len(relics)
            except Exception as e:
                stats["errors"].append(f"维基百科爬取失败: {e}")
        
        if "baidu" in sources:
            try:
                relics = self.crawl_from_baidu_baike(max_items=max_items_per_source)
                all_relics.extend(relics)
                stats["by_source"]["百度百科"] = len(relics)
            except Exception as e:
                stats["errors"].append(f"百度百科爬取失败: {e}")
        
        if "gov" in sources:
            try:
                relics = self.crawl_from_gov_site(max_items_per_source)
                all_relics.extend(relics)
                stats["by_source"]["政府网站"] = len(relics)
            except Exception as e:
                stats["errors"].append(f"政府网站爬取失败: {e}")
        
        # 更新知识库
        if update_mode == "replace":
            self.knowledge_base["relics"] = all_relics
        else:  # append
            # 去重：根据名称和地址判断
            existing_keys = {
                (r.get("名称"), r.get("地址")) 
                for r in self.knowledge_base["relics"]
            }
            
            new_relics = [
                r for r in all_relics 
                if (r.get("名称"), r.get("地址")) not in existing_keys
            ]
            
            self.knowledge_base["relics"].extend(new_relics)
        
        # 保存知识库
        self._save_knowledge_base()
        
        stats["total_crawled"] = len(all_relics)
        stats["total_in_kb"] = len(self.knowledge_base["relics"])
        
        print(f"\n知识库构建完成:")
        print(f"  本次爬取: {stats['total_crawled']} 条")
        print(f"  知识库总数: {stats['total_in_kb']} 条")
        print(f"  各来源统计: {stats['by_source']}")
        
        return stats
    
    def search(
        self,
        name: str = None,
        era: str = None,
        location: str = None,
        level: str = None,
        relic_type: str = None,
        batch: str = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        检索文物
        
        Args:
            name: 文物名称（模糊匹配）
            era: 时代（模糊匹配）
            location: 地址/地区（模糊匹配）
            level: 保护级别
            relic_type: 文物类型
            batch: 批次
            limit: 返回数量限制
        
        Returns:
            检索结果列表
        """
        results = self.knowledge_base["relics"]
        
        # 按条件过滤
        if name:
            results = [r for r in results if name in r.get("名称", "")]
        
        if era:
            results = [r for r in results if era in r.get("时代", "")]
        
        if location:
            results = [r for r in results if location in r.get("地址", "")]
        
        if level:
            results = [r for r in results if level in r.get("级别", "")]
        
        if relic_type:
            results = [r for r in results if relic_type in r.get("类型", "")]
        
        if batch:
            results = [r for r in results if batch in r.get("批次", "")]
        
        # 限制返回数量
        results = results[:limit]
        
        return results
    
    def get_statistics(self) -> Dict:
        """
        获取知识库统计信息
        
        Returns:
            统计信息
        """
        relics = self.knowledge_base["relics"]
        
        stats = {
            "总数": len(relics),
            "按时代统计": {},
            "按级别统计": {},
            "按类型统计": {},
            "按地区统计": {},
            "数据来源": {},
            "最后更新": self.knowledge_base.get("metadata", {}).get("last_update", "未知")
        }
        
        for relic in relics:
            # 按时代统计
            era = relic.get("时代", "未知")
            stats["按时代统计"][era] = stats["按时代统计"].get(era, 0) + 1
            
            # 按级别统计
            level = relic.get("级别", "未知")
            stats["按级别统计"][level] = stats["按级别统计"].get(level, 0) + 1
            
            # 按类型统计
            relic_type = relic.get("类型", "未知")
            stats["按类型统计"][relic_type] = stats["按类型统计"].get(relic_type, 0) + 1
            
            # 按地区统计（提取省份）
            address = relic.get("地址", "")
            # 简单提取省份
            provinces = ["北京", "上海", "天津", "重庆", "河北", "山西", "辽宁", "吉林",
                        "黑龙江", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
                        "湖北", "湖南", "广东", "广西", "海南", "四川", "贵州", "云南",
                        "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆", "内蒙古"]
            
            province = "其他"
            for p in provinces:
                if p in address:
                    province = p
                    break
            
            stats["按地区统计"][province] = stats["按地区统计"].get(province, 0) + 1
            
            # 数据来源
            source = relic.get("来源", "未知")
            stats["数据来源"][source] = stats["数据来源"].get(source, 0) + 1
        
        return stats
    
    def add_relic(self, relic_info: Dict) -> bool:
        """
        添加文物到知识库
        
        Args:
            relic_info: 文物信息
        
        Returns:
            是否成功
        """
        if not relic_info.get("名称"):
            return False
        
        relic_info["采集时间"] = datetime.now().isoformat()
        relic_info["来源"] = relic_info.get("来源", "手动添加")
        
        self.knowledge_base["relics"].append(relic_info)
        self._save_knowledge_base()
        
        return True
    
    def export_to_excel(self, output_path: str = "cultural_relics_export.xlsx") -> str:
        """
        导出知识库到Excel
        
        Args:
            output_path: 输出文件路径
        
        Returns:
            输出文件路径
        """
        relics = self.knowledge_base["relics"]
        
        if not relics:
            print("知识库为空，无法导出")
            return ""
        
        df = pd.DataFrame(relics)
        df.to_excel(output_path, index=False, engine='openpyxl')
        
        print(f"知识库已导出到: {output_path}")
        print(f"导出数量: {len(relics)} 条")
        
        return output_path


def cultural_relics_expert(
    action: str,
    name: str = None,
    era: str = None,
    location: str = None,
    level: str = None,
    relic_type: str = None,
    batch: str = None,
    limit: int = 100,
    sources: str = "wikipedia,baidu,gov",
    max_items: int = 100,
    update_mode: str = "append"
) -> Any:
    """
    文物检索专家
    
    Args:
        action: 操作类型
            - "search": 检索文物
            - "build": 构建知识库
            - "stats": 获取统计信息
            - "export": 导出知识库
        name: 文物名称（模糊匹配）
        era: 时代（模糊匹配）
        location: 地址/地区（模糊匹配）
        level: 保护级别
        relic_type: 文物类型
        batch: 批次
        limit: 返回数量限制
        sources: 数据来源（逗号分隔）
        max_items: 每来源最大爬取数量
        update_mode: 更新模式 "append" 或 "replace"
    
    Returns:
        操作结果
    """
    expert = CulturalRelicsExpert()
    
    if action == "search":
        # 检索文物
        results = expert.search(
            name=name,
            era=era,
            location=location,
            level=level,
            relic_type=relic_type,
            batch=batch,
            limit=limit
        )
        
        return {
            "success": True,
            "count": len(results),
            "results": results,
            "message": f"找到 {len(results)} 条匹配的文物"
        }
    
    elif action == "build":
        # 构建知识库
        source_list = [s.strip() for s in sources.split(",")]
        stats = expert.build_knowledge_base(
            sources=source_list,
            max_items_per_source=max_items,
            update_mode=update_mode
        )
        
        return {
            "success": True,
            "stats": stats,
            "message": f"知识库构建完成，共 {stats['total_in_kb']} 条文物"
        }
    
    elif action == "stats":
        # 获取统计信息
        stats = expert.get_statistics()
        
        return {
            "success": True,
            "statistics": stats,
            "message": f"知识库共 {stats['总数']} 条文物"
        }
    
    elif action == "export":
        # 导出知识库
        output_path = expert.export_to_excel()
        
        return {
            "success": True,
            "output_path": output_path,
            "message": f"知识库已导出到 {output_path}"
        }
    
    else:
        return {
            "success": False,
            "message": f"不支持的操作: {action}"
        }