# -*- coding: utf-8 -*-
"""
Hermes AI Agent 启动脚本
"""
import asyncio
import os
import sys

# 设置控制台编码
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# 设置环境变量 - 请替换为你的 API Key
# os.environ["OPENAI_API_KEY"] = "your-api-key-here"

from hermes.core import Agent
from hermes.web import hermes_web


async def main():
    # 创建一个简单的 Agent
    # 注意: 需要设置 API Key 才能正常使用
    # 支持的 provider: openai, azure, anthropic, gemini, google
    agent = Agent(
        provider="openai",           # 支持: openai, azure, anthropic, gemini, google
        model="gpt-4o-mini",         # 模型名称
        name="Hermes Assistant",     # Agent 名称
        description="A helpful AI assistant powered by Hermes",  # 描述
        prompt="You are a helpful AI assistant. Be concise and helpful.",  # 系统提示
        temperature=0.7,             # 温度参数
        debug=True,                  # 开启调试模式
    )
    
    print("=" * 50)
    print("Starting Hermes AI Agent Web Interface...")
    print("=" * 50)
    print(f"Provider: {agent.provider}")
    print(f"Model: {agent.model}")
    print(f"Name: {agent.name}")
    print("=" * 50)
    print("Web interface will be available at: http://localhost:8000")
    print("=" * 50)
    
    # 启动 Web 界面
    await hermes_web(port=8000, agent=agent)


if __name__ == "__main__":
    # 检查是否设置了 API Key
    if not os.environ.get("OPENAI_API_KEY"):
        print("\n" + "=" * 50)
        print("WARNING: OPENAI_API_KEY environment variable not set")
        print("=" * 50)
        print("Please set the environment variable before running:")
        print("  Windows: set OPENAI_API_KEY=your-key")
        print("  Linux/Mac: export OPENAI_API_KEY=your-key")
        print("\nOr uncomment and fill in the API Key in the script")
        print("=" * 50 + "\n")
    
    asyncio.run(main())
