"""
OpenClaw 使用演示
OpenClaw 是一个开源的智能体编排插件，基于 CMDOP Python SDK
"""

from openclaw import OpenClaw, AsyncOpenClaw, CMDOPClient
import openclaw

print("=" * 60)
print("OpenClaw 功能演示")
print("=" * 60)

# 1. 显示版本信息
print(f"\n1. 版本信息:")
print(f"   OpenClaw 版本: {openclaw.__version__}")
print(f"   文档地址: https://cmdop.com/docs/sdk/python/")

# 2. 显示主要类和功能
print(f"\n2. 主要类:")
print(f"   - OpenClaw: 同步客户端")
print(f"   - AsyncOpenClaw: 异步客户端")
print(f"   - CMDOPClient: CMDOP 基础客户端")

# 3. 显示 OpenClaw 的主要方法
print(f"\n3. OpenClaw 主要方法:")
methods = ['agent', 'close', 'download', 'extract', 'files', 
           'from_transport', 'is_connected', 'local', 'mode', 
           'remote', 'skills', 'terminal', 'transport']
for method in methods:
    print(f"   - {method}()")

# 4. 显示异常类
print(f"\n4. 异常类:")
exceptions = ['AuthenticationError', 'CMDOPError', 'ConnectionError', 'TimeoutError']
for exc in exceptions:
    print(f"   - {exc}")

# 5. 使用示例说明
print(f"\n5. 使用示例:")
print("""
   # 创建客户端（需要配置传输层）
   from openclaw import OpenClaw
   
   # 使用工厂方法创建客户端
   client = OpenClaw.from_transport(transport)
   
   # 检查连接状态
   if client.is_connected():
       print("已连接")
   
   # 使用各种功能
   client.agent()      # 智能体操作
   client.files()      # 文件操作
   client.skills()     # 技能操作
   client.terminal()   # 终端操作
   client.extract()    # 提取操作
   client.download()   # 下载操作
   
   # 关闭连接
   client.close()
""")

print("\n" + "=" * 60)
print("演示完成！")
print("=" * 60)
print("\n注意: 实际使用需要配置正确的传输层(transport)和认证信息。")
print("详细文档请访问: https://cmdop.com/docs/sdk/python/")
