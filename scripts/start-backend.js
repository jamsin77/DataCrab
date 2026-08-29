#!/usr/bin/env node
/**
 * DataCrab 跨平台后端启动脚本
 *
 * 解决问题：package.json 硬编码 Windows 路径 `.venv\Scripts\python.exe`，
 *   Linux/Mac 上找不到命令导致后端起不来。
 *
 * 查找 Python 顺序：
 *   1. backend/.venv 虚拟环境（Win: .venv\Scripts\python.exe / Unix: .venv/bin/python）
 *   2. 系统已装到全局的 DataCrab（pip install -e ./backend 装过）
 *   3. 系统 Python（python3 / python / py -3）
 *
 * 用法：
 *   node scripts/start-backend.js [--reload] [--host 0.0.0.0] [--port 8000] ...
 *
 * 透传所有参数给 uvicorn，支持 --reload（dev）和不带（start）两种模式。
 */

const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

const ROOT = path.resolve(__dirname, "..");
const BACKEND = path.join(ROOT, "backend");
const isWin = process.platform === "win32";

/**
 * 检查命令是否存在且版本 ≥ 3.11
 */
function checkPython(cmd) {
  const { spawnSync } = require("child_process");
  const v = spawnSync(cmd, ["--version"], {
    encoding: "utf8",
    shell: isWin,
    stdio: ["ignore", "pipe", "pipe"],
  });
  if (v.status !== 0 || !v.stdout) return null;
  const m = v.stdout.trim().match(/^(\d+)\.(\d+)\.(\d+)/);
  if (!m) return null;
  const major = +m[1];
  const minor = +m[2];
  if (major !== 3 || minor < 11) return { ok: false, version: m[0] };
  return { ok: true, version: m[0] };
}

/**
 * 查找可用的 Python 解释器
 * 顺序：venv → 系统 python3 → 系统 python → Windows py launcher
 */
function findPython() {
  // 1. 虚拟环境 venv（首选）
  const venvPy = isWin
    ? path.join(BACKEND, ".venv", "Scripts", "python.exe")
    : path.join(BACKEND, ".venv", "bin", "python");
  if (fs.existsSync(venvPy)) {
    return { cmd: venvPy, source: "venv" };
  }

  // 2. 系统已安装的 DataCrab（pip install -e 装到全局 / 用户站点）
  //    用 python -c 检测能否 import app.main
  const systemCandidates = isWin
    ? ["python", "py -3"]
    : ["python3", "python"];
  for (const c of systemCandidates) {
    const parts = c.includes(" ") ? c.split(" ") : [c];
    const check = checkPython(parts[0]);
    if (check) {
      if (check.ok) return { cmd: parts[0], args: parts.slice(1), source: "system" };
      console.warn(`  [skip] ${c}: 版本 ${check.version} 不满足 3.11+`);
    }
  }

  return null;
}

function main() {
  const py = findPython();
  if (!py) {
    console.error("");
    console.error("✗ 未找到可用的 Python 3.11+ 解释器。");
    console.error("  解决方法：");
    console.error("    1. 先执行 npm install（自动创建 venv 并安装依赖）");
    console.error("    2. 或手动创建虚拟环境：cd backend && python3 -m venv .venv");
    console.error("       激活后执行: pip install -e .");
    console.error("");
    process.exit(1);
  }

  const cmd = py.cmd;
  const preArgs = py.args || [];
  // uvicorn 参数：透传命令行额外参数（--reload / --host / --port 等）
  const extraArgs = process.argv.slice(2);
  const uvicornArgs = [
    ...preArgs,
    "-m",
    "uvicorn",
    "app.main:app",
    "--host",
    "0.0.0.0",
    "--port",
    "8000",
    ...extraArgs,
  ];

  console.log(`[DataCrab] 启动后端：${cmd} ${uvicornArgs.join(" ")}`);

  const child = spawn(cmd, uvicornArgs, {
    cwd: BACKEND,
    stdio: "inherit",
    shell: isWin,
  });

  child.on("exit", (code) => process.exit(code ?? 1));
}

main();
