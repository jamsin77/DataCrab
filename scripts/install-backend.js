#!/usr/bin/env node
/**
 * DataCrab 跨平台后端依赖安装脚本
 *
 * 由 `npm install` 的 postinstall 钩子调用。
 * 解决问题：
 *   1. 系统 `pip` 可能绑定到旧版 Python（如 CentOS 默认 python3.6），
 *      直接 `pip install -e ./backend` 会因 requires-python 失败或卡住。
 *   2. Windows 下 `pip` / `python` 不一定在 PATH。
 *   3. 缺少 Python 版本 / sqlite3 模块可用性检测，报错信息不友好。
 *
 * 流程：依次尝试 py -3 / python3 / python → 检测版本 ≥ 3.11 →
 *      检测 sqlite3 模块 → `python -m pip install -e ./backend[all]` → 失败回退核心依赖。
 */

const { spawnSync } = require("child_process");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const BACKEND = path.join(ROOT, "backend");
const MIN_MAJOR = 3;
const MIN_MINOR = 11;

const isWin = process.platform === "win32";

function run(cmd, args, opts = {}) {
  return spawnSync(cmd, args, { encoding: "utf8", shell: isWin, ...opts });
}

function tryPython(cmd) {
  const versionRe = /^(\d+)\.(\d+)\.(\d+)/;
  const v = run(cmd, ["--version"], { stdio: ["ignore", "pipe", "pipe"] });
  if (v.status !== 0 || !v.stdout) return null;
  const m = v.stdout.trim().match(versionRe);
  if (!m) return null;
  const major = +m[1];
  const minor = +m[2];
  if (major !== MIN_MAJOR || minor < MIN_MINOR) {
    return { ok: false, reason: `版本 ${m[0]} 低于要求 ${MIN_MAJOR}.${MIN_MINOR}+` };
  }
  const sqlite = run(cmd, ["-c", "import sqlite3; print(sqlite3.sqlite_version)"], {
    stdio: ["ignore", "pipe", "pipe"],
  });
  if (sqlite.status !== 0) {
    return { ok: false, reason: "缺少 sqlite3 模块（Python 编译时未启用 sqlite 支持）" };
  }
  return { ok: true, version: m[0], sqlite: sqlite.stdout.trim() };
}

function findPython() {
  const candidates = [];
  if (isWin) {
    candidates.push("py");          // Windows py launcher（推荐）
    candidates.push("python");      // 常见
  } else {
    candidates.push("python3");     // Unix 标准
    candidates.push("python");      // 兜底
  }
  for (const c of candidates) {
    const r = tryPython(c);
    if (r) {
      if (r.ok) return { cmd: c, ...r };
      console.warn(`  [skip] ${c}: ${r.reason}`);
    }
  }
  return null;
}

function main() {
  console.log("\n[DataCrab] 检测 Python 运行环境 ...");

  const py = findPython();
  if (!py) {
    console.error("");
    console.error("✗ 未找到满足条件的 Python 解释器。");
    console.error(`  要求：Python ${MIN_MAJOR}.${MIN_MINOR}+ 且包含 sqlite3 模块。`);
    console.error("");
    console.error("  解决方法：");
    if (isWin) {
      console.error("    1. 安装 Python 3.11+：https://www.python.org/downloads/");
      console.error('    2. 安装时勾选 "Add Python to PATH"。');
      console.error("    3. 重新执行 npm install。");
    } else {
      console.error("    1. 安装 Python 3.11+（Debian/Ubuntu: apt install python3.11 python3.11-venv");
      console.error("       RHEL/CentOS/Alibaba Cloud Linux: 可用 dnf 或从 python.org 编译）。");
      console.error("    2. 若 Python 已是 3.11+ 但报缺 sqlite3：装 sqlite-devel/libsqlite3-dev 后重编译 Python。");
      console.error("    3. 重新执行 npm install。");
    }
    process.exit(1);
  }

  console.log(`  [ok] ${py.cmd} → Python ${py.version} (sqlite ${py.sqlite})`);

  console.log("\n[DataCrab] 安装后端依赖 (pip install -e ./backend) ...");
  const install = run(py.cmd, ["-m", "pip", "install", "-e", BACKEND], {
    stdio: "inherit",
  });
  if (install.status !== 0) {
    console.warn("\n[DataCrab] 完整安装失败，尝试仅安装核心依赖 (requirements.txt) ...");
    const req = path.join(BACKEND, "requirements.txt");
    const fallback = run(py.cmd, ["-m", "pip", "install", "-r", req], { stdio: "inherit" });
    if (fallback.status !== 0) {
      console.error("\n✗ 后端依赖安装失败。请手动执行：");
      console.error(`    ${py.cmd} -m pip install -e ./backend`);
      process.exit(1);
    }
  }

  console.log("\n[DataCrab] 后端依赖安装完成。");
}

main();
