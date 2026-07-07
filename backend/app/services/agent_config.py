"""Agent配置管理"""

from pathlib import Path
from typing import Optional
import re


class AgentConfig:
    """Agent配置类"""
    
    def __init__(self):
        self.name = "DataCrab"
        self.short_name = "DC"
        self.full_name = "DataCrab 数据工程智能体"
        self._load_from_md()
    
    def _load_from_md(self):
        """从personal.md加载配置"""
        try:
            md_path = Path(__file__).parent / "personal.md"
            if not md_path.exists():
                return
            
            content = md_path.read_text(encoding='utf-8')
            
            # 解析名称配置
            name_match = re.search(r'\*\*名称\*\*:\s*(.+)', content)
            if name_match:
                self.name = name_match.group(1).strip()
            
            short_name_match = re.search(r'\*\*简称\*\*:\s*(.+)', content)
            if short_name_match:
                self.short_name = short_name_match.group(1).strip()
            
            full_name_match = re.search(r'\*\*全称\*\*:\s*(.+)', content)
            if full_name_match:
                self.full_name = full_name_match.group(1).strip()
                
        except Exception as e:
            print(f"加载Agent配置失败: {e}")
    
    def to_dict(self):
        """转换为字典"""
        return {
            "name": self.name,
            "short_name": self.short_name,
            "full_name": self.full_name,
        }


# 全局配置实例
agent_config = AgentConfig()