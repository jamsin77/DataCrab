# -*- coding: utf-8 -*-
"""
Hermes AI Agent 启动脚本 - GLM-5 版本
使用智谱 AI 的 GLM-5 大模型

使用前请设置环境变量:
  set ZHIPUAI_API_KEY=your-api-key

获取 API Key: https://open.bigmodel.cn/
"""
import asyncio
import os
import sys

# 设置控制台编码
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# 设置 API Key
os.environ["ZHIPUAI_API_KEY"] = "882e722bb8054bada3da404143ce3d1c.0WTzuejAQ0fQ6gKL"

# 检查并安装 zhipuai
try:
    from zhipuai import ZhipuAI
except ImportError:
    print("Installing zhipuai...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "zhipuai"])
    from zhipuai import ZhipuAI

from hermes.web import hermes_web
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import tempfile
import shutil
import importlib.resources as pkg_resources
import hermes.web_interface


class GLM5Agent:
    """使用 GLM-5 的 Agent"""
    
    def __init__(
        self,
        model="glm-4-flash",
        name="GLM-5 Assistant",
        description="A helpful AI assistant powered by GLM-5",
        prompt="You are a helpful AI assistant. Be concise and helpful.",
        temperature=0.7,
        debug=True,
    ):
        self.provider = "zhipuai"
        self.model = model
        self.name = name
        self.description = description
        self.prompt = prompt
        self.temperature = temperature
        self.debug = debug
        
        # 获取 API Key
        self.api_key = os.environ.get("ZHIPUAI_API_KEY", "")
        if not self.api_key:
            raise ValueError("请设置环境变量 ZHIPUAI_API_KEY")
        
        # 初始化 ZhipuAI 客户端
        self.client = ZhipuAI(api_key=self.api_key)
        
        if self.debug:
            print(f"GLM-5 Agent initialized:")
            print(f"  Model: {self.model}")
            print(f"  Name: {self.name}")
    
    async def execute(self, input_data=None, chat_history=None):
        """执行对话"""
        try:
            # 构建消息列表
            messages = []
            
            # 添加系统提示
            messages.append({
                "role": "system",
                "content": self.prompt
            })
            
            # 添加历史消息
            if chat_history:
                for msg in chat_history:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if role in ["user", "assistant"]:
                        messages.append({"role": role, "content": content})
            
            # 添加当前用户消息
            if input_data:
                messages.append({"role": "user", "content": input_data})
            
            if self.debug:
                print(f"\nSending request to GLM-5...")
                print(f"Messages count: {len(messages)}")
            
            # 调用 GLM-5 API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
            )
            
            # 提取响应内容
            content = response.choices[0].message.content
            
            if self.debug:
                print(f"Response received: {content[:100]}...")
            
            return content
            
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            if self.debug:
                print(f"\nError: {error_msg}")
            return error_msg


async def hermes_web_glm(port: int = 8000, agent=None):
    """启动 Web 界面"""
    app = FastAPI()
    
    # CORS 配置
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # 聊天路由
    @app.post("/chat")
    async def chat(request: Request):
        data = await request.json()
        message = data.get("message", "")
        chat_history = data.get("chat_history", [])
        
        if not message:
            return JSONResponse({"error": "Empty message"}, status_code=400)
        
        if agent is None:
            return JSONResponse({"error": "Agent not available"}, status_code=500)
        
        response = await agent.execute(input_data=message, chat_history=chat_history)
        return response
    
    # 创建临时目录用于静态文件
    temp_dir = tempfile.mkdtemp()
    
    # 复制 Vue 构建文件
    dist_path = pkg_resources.files(hermes.web_interface) / "dist"
    for item in dist_path.iterdir():
        dest_path = os.path.join(temp_dir, item.name)
        if item.is_dir():
            shutil.copytree(item, dest_path)
        else:
            shutil.copy2(item, dest_path)
    
    # 挂载静态文件
    app.mount("/", StaticFiles(directory=temp_dir, html=True), name="static")
    
    print(f"Starting web server on port {port}...")
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    # 创建 GLM-5 Agent
    agent = GLM5Agent(
        model="glm-4-flash",        # 可选: glm-4, glm-4-flash, glm-4-plus
        name="GLM-5 Assistant",
        description="A helpful AI assistant powered by GLM-5",
        prompt="You are a helpful AI assistant. Be concise and helpful.",
        temperature=0.7,
        debug=True,
    )
    
    print("=" * 50)
    print("Starting Hermes AI Agent with GLM-5...")
    print("=" * 50)
    print(f"Provider: {agent.provider}")
    print(f"Model: {agent.model}")
    print(f"Name: {agent.name}")
    print("=" * 50)
    print("Web interface: http://localhost:8000")
    print("=" * 50)
    
    # 启动 Web 界面
    await hermes_web_glm(port=8000, agent=agent)


if __name__ == "__main__":
    # 检查 API Key
    if not os.environ.get("ZHIPUAI_API_KEY"):
        print("\n" + "=" * 50)
        print("WARNING: ZHIPUAI_API_KEY not set!")
        print("=" * 50)
        print("Please set the environment variable:")
        print("  Windows: set ZHIPUAI_API_KEY=your-api-key")
        print("  Linux/Mac: export ZHIPUAI_API_KEY=your-api-key")
        print("\nGet your API Key from: https://open.bigmodel.cn/")
        print("=" * 50 + "\n")
    
    asyncio.run(main())
