"""DataCrab 启动器（Windows 安装版）

职责：
  1. 选一个空闲端口（默认 8000，被占则顺延 +1，最多试 20 个）
  2. 设置 DATACRAB_API_BASE（技能沙箱子进程靠它回连主进程，必须与实际端口一致）
  3. 启动 uvicorn（前后端同端口，FastAPI 托管 frontend/dist）
  4. 健康检查通过后自动打开浏览器

环境变量（均可在启动前覆盖）：
  DATACRAB_PORT        起始端口，默认 8000
  DATACRAB_HOST        监听地址，默认 127.0.0.1（仅本机访问；设 0.0.0.0 允许局域网）
  DATACRAB_NO_BROWSER  设为 1 不自动打开浏览器
"""

import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(ROOT, "backend")

PREFERRED_PORT = int(os.environ.get("DATACRAB_PORT", "8000"))
HOST = os.environ.get("DATACRAB_HOST", "127.0.0.1")
NO_BROWSER = os.environ.get("DATACRAB_NO_BROWSER", "") == "1"


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _pick_port(preferred: int) -> int:
    for p in range(preferred, preferred + 20):
        if not _port_in_use(p):
            return p
    print(f"[DataCrab] 端口 {preferred}~{preferred + 19} 均被占用。")
    print(f"[DataCrab] 请设置环境变量 DATACRAB_PORT 指定一个空闲端口后重试。")
    sys.exit(1)


def _open_browser_when_ready(port: int) -> None:
    url = f"http://127.0.0.1:{port}"
    for _ in range(120):  # 最多等 2 分钟
        try:
            urllib.request.urlopen(f"{url}/health", timeout=1)
            if not NO_BROWSER:
                print(f"[DataCrab] 服务就绪，打开浏览器: {url}")
                webbrowser.open(url)
            else:
                print(f"[DataCrab] 服务就绪: {url}")
            return
        except Exception:
            time.sleep(1)
    print(f"[DataCrab] 服务 2 分钟内未就绪，请查看上方日志。手动访问: {url}")


def main() -> None:
    port = _pick_port(PREFERRED_PORT)
    # 技能沙箱子进程回连地址必须与实际监听端口一致
    os.environ["DATACRAB_API_BASE"] = f"http://127.0.0.1:{port}"
    # 数据库 / 日志 / uploads 等路径按 backend/ 锚定或相对 cwd，统一切过去
    os.chdir(BACKEND_DIR)

    print(f"[DataCrab] 安装目录: {ROOT}")
    print(f"[DataCrab] 启动服务: http://{HOST}:{port}  (Ctrl+C 停止)")
    threading.Thread(target=_open_browser_when_ready, args=(port,), daemon=True).start()

    import uvicorn
    uvicorn.run("app.main:app", host=HOST, port=port, log_level="info")


if __name__ == "__main__":
    main()
