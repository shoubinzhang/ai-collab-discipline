#!/usr/bin/env python3
"""
check_file_size_limits.py · 文件规模红线 CI 检查（L4 CI 门禁层核心脚本）

定义在 CLAUDE.md「文件规模红线」章节的限额，转成可执行的 CI 检查。

使用方式：
    # 全仓库扫描，报告所有违规
    python3 scripts/ci/check_file_size_limits.py --report

    # 仅检查 git staged 文件（CI / pre-commit 用）
    python3 scripts/ci/check_file_size_limits.py --staged

    # PreToolUse hook 用（读环境变量，不阻塞）
    python3 scripts/ci/check_file_size_limits.py --pretool

    # 与基线对比，仅报"新增违规"
    python3 scripts/ci/check_file_size_limits.py --vs-baseline baseline.json

退出码：
    0 — 没有 hard 违规
    1 — 有新增 hard 违规（CI 应 fail）
    2 — 有 warning 违规（信息性，CI 视配置）

可独立运行，无外部依赖。Python 3.8+。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# ─────────────────────────────────────────────────────────────────────────────
# 限额配置 — 与 CLAUDE.md「文件规模红线」表格对齐
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Limit:
    name: str          # 文件类别人类可读名
    warning: int       # 警戒线
    hard: int          # 硬上限

LIMITS = {
    "frontend_page":      Limit("前端页面",          400, 600),
    "frontend_component": Limit("前端通用组件",       300, 500),
    "backend_router":     Limit("后端路由",           500, 800),
    "backend_service":    Limit("后端 service",       600, 1000),
    "migration":          Limit("数据库迁移",         400, 600),
    "default":            Limit("其他",               800, 1500),
}


# ─────────────────────────────────────────────────────────────────────────────
# 文件分类 — 按路径启发式归类
# ─────────────────────────────────────────────────────────────────────────────

def classify(rel_path: str) -> str:
    """根据相对路径推断文件类别。可在你项目里 fork 后调整。"""
    p = rel_path.replace("\\", "/")

    # 数据库迁移
    if "/migrations/versions/" in p or "/alembic/versions/" in p:
        return "migration"

    # 后端
    if p.endswith(".py"):
        if "/routers/" in p or "/routes/" in p or "/api/" in p:
            return "backend_router"
        if "/services/" in p:
            return "backend_service"
        return "default"

    # 前端
    if p.endswith((".jsx", ".tsx")):
        if "/pages/" in p:
            return "frontend_page"
        if "/components/" in p:
            return "frontend_component"
        return "frontend_component"

    if p.endswith((".js", ".ts")):
        if "/pages/" in p:
            return "frontend_page"
        return "default"

    return "default"


# ─────────────────────────────────────────────────────────────────────────────
# 行数统计 — 真实物理行（不去 blank、不去 comment，与 wc -l 对齐）
# ─────────────────────────────────────────────────────────────────────────────

# 应跳过的目录/文件
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".pytest_cache",
    ".venv", "venv", "build", "dist", ".next", "coverage",
}
SKIP_FILE_EXT = {".min.js", ".min.css", ".lock", ".log"}

def is_relevant_file(path: Path) -> bool:
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    name = path.name
    if any(name.endswith(ext) for ext in SKIP_FILE_EXT):
        return False
    if path.suffix not in {".py", ".js", ".ts", ".jsx", ".tsx"}:
        return False
    return True

def count_lines(path: Path) -> int:
    try:
        with path.open("rb") as f:
            return sum(1 for _ in f)
    except (OSError, IOError) as e:
        print(f"[warn] cannot read {path}: {e}", file=sys.stderr)
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# 扫描入口
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Violation:
    path: str
    category: str
    lines: int
    limit: Limit
    severity: str  # "hard" | "warning"

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "category": self.category,
            "lines": self.lines,
            "warning": self.limit.warning,
            "hard": self.limit.hard,
            "severity": self.severity,
        }

def scan_paths(paths: Iterable[Path], project_root: Path) -> list[Violation]:
    """对一组文件生成违规列表。"""
    violations: list[Violation] = []
    for path in paths:
        if not path.is_file() or not is_relevant_file(path):
            continue
        rel = str(path.relative_to(project_root))
        category = classify(rel)
        limit = LIMITS.get(category, LIMITS["default"])
        lines = count_lines(path)
        if lines >= limit.hard:
            violations.append(Violation(rel, category, lines, limit, "hard"))
        elif lines >= limit.warning:
            violations.append(Violation(rel, category, lines, limit, "warning"))
    return violations

def walk_project(project_root: Path) -> list[Path]:
    """遍历整个项目（跳过 SKIP_DIRS）。"""
    found: list[Path] = []
    for base, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            found.append(Path(base) / f)
    return found

def get_staged_files(project_root: Path) -> list[Path]:
    """获取 git staged 的文件。"""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            cwd=project_root, text=True, stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [project_root / line.strip() for line in out.splitlines() if line.strip()]


# ─────────────────────────────────────────────────────────────────────────────
# 输出格式化
# ─────────────────────────────────────────────────────────────────────────────

def print_violations(vs: list[Violation], header: str = "") -> None:
    if header:
        print(f"\n=== {header} ===")
    if not vs:
        print("  (none)")
        return
    # 按严重度 + 行数倒序
    vs_sorted = sorted(vs, key=lambda v: (v.severity != "hard", -v.lines))
    for v in vs_sorted:
        marker = "🚨" if v.severity == "hard" else "⚠️ "
        print(f"  {marker} {v.path}")
        print(f"     {v.lines} lines · {v.limit.name} · "
              f"warning={v.limit.warning} hard={v.limit.hard}")

def summary(vs: list[Violation]) -> tuple[int, int]:
    hard = sum(1 for v in vs if v.severity == "hard")
    warn = sum(1 for v in vs if v.severity == "warning")
    return hard, warn


# ─────────────────────────────────────────────────────────────────────────────
# 子命令
# ─────────────────────────────────────────────────────────────────────────────

def cmd_report(project_root: Path) -> int:
    """全仓库扫描，打印报告。退出码 0（仅信息性）。"""
    files = walk_project(project_root)
    vs = scan_paths(files, project_root)
    hard, warn = summary(vs)

    print(f"📊 文件规模检查 · 项目：{project_root}")
    print(f"   扫描文件数：{len(files)}")
    print(f"   硬上限违规：{hard}")
    print(f"   警戒线违规：{warn}")

    print_violations([v for v in vs if v.severity == "hard"], "硬上限违规（不能加新功能）")
    print_violations([v for v in vs if v.severity == "warning"], "警戒线违规（建议拆分）")

    return 0

def cmd_staged(project_root: Path) -> int:
    """检查 git staged 文件。新增 hard 违规则 fail。"""
    staged = get_staged_files(project_root)
    if not staged:
        print("✅ 没有 staged 文件需要检查")
        return 0

    vs = scan_paths(staged, project_root)
    hard, warn = summary(vs)

    print(f"📊 Staged 文件规模检查（{len(staged)} 个文件）")
    print_violations([v for v in vs if v.severity == "hard"], "硬上限违规")
    print_violations([v for v in vs if v.severity == "warning"], "警戒线违规")

    if hard:
        print(f"\n🚨 发现 {hard} 个硬上限违规 — CI 失败")
        print("   按 CLAUDE.md「修改已超标文件的强制条款」：")
        print("   修改超标文件时必须同次拆分至少一个子组件，原文件行数必须减少。")
        return 1
    if warn:
        print(f"\n⚠️ 发现 {warn} 个警戒线违规（不阻塞 CI）")
        return 2
    print("\n✅ 全部在限内")
    return 0

def cmd_pretool(project_root: Path) -> int:
    """PreToolUse hook 模式。Claude Code 在 Edit/Write 前调用，仅打印提示，不阻塞。"""
    # 通过环境变量获取 Claude Code 即将编辑的文件路径
    # （不同版本可能有不同变量名，这里取最常见的）
    target = (
        os.environ.get("CLAUDE_TOOL_FILE_PATH")
        or os.environ.get("CLAUDE_TOOL_PATH")
        or ""
    )
    if not target:
        # 没有目标文件信息，silent 退出
        return 0

    target_path = Path(target)
    if not target_path.is_absolute():
        target_path = project_root / target_path
    if not target_path.exists():
        return 0  # 新建文件，无法预知大小

    rel = str(target_path.relative_to(project_root)) if str(target_path).startswith(str(project_root)) else target
    category = classify(rel)
    limit = LIMITS.get(category, LIMITS["default"])
    lines = count_lines(target_path)

    if lines >= limit.hard:
        print(f"🚨 [pretool] {rel} 已 {lines} 行（{limit.name}），超过硬上限 {limit.hard}")
        print(f"   按 CLAUDE.md：禁止直接加新功能。请先拆分。")
    elif lines >= limit.warning:
        print(f"⚠️ [pretool] {rel} 已 {lines} 行（{limit.name}），超过警戒线 {limit.warning}")
        print(f"   建议本次修改顺手拆一部分。")
    return 0

def cmd_vs_baseline(project_root: Path, baseline_file: Path) -> int:
    """与基线对比。仅当出现新违规时 fail。"""
    if not baseline_file.exists():
        print(f"❌ baseline 文件不存在：{baseline_file}", file=sys.stderr)
        return 3

    baseline = json.loads(baseline_file.read_text())
    baseline_set = {(v["path"], v["severity"]) for v in baseline.get("violations", [])}

    files = walk_project(project_root)
    vs = scan_paths(files, project_root)
    current_set = {(v.path, v.severity) for v in vs}

    new_hard = [v for v in vs
                if v.severity == "hard" and (v.path, v.severity) not in baseline_set]
    fixed = baseline_set - current_set

    print(f"📊 vs baseline ({baseline_file.name})")
    print(f"   基线违规数：{len(baseline_set)}")
    print(f"   当前违规数：{len(current_set)}")
    print(f"   新增 hard：{len(new_hard)}")
    print(f"   已修复：{len(fixed)}")

    if new_hard:
        print_violations(new_hard, "新增的硬上限违规")
        return 1
    print("\n✅ 没有新增 hard 违规")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    # Windows 终端默认 GBK，print 里的 emoji / 中文会 UnicodeEncodeError；
    # CI（Linux）默认 UTF-8 不受影响。统一切 UTF-8，保证本地 + CI 都能跑。
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        description="文件规模红线检查（CLAUDE.md 定义的硬上限 / 警戒线）"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--report", action="store_true", help="全仓库扫描")
    group.add_argument("--staged", action="store_true", help="仅检查 git staged 文件")
    group.add_argument("--pretool", action="store_true", help="PreToolUse hook 模式")
    group.add_argument("--vs-baseline", type=Path, help="与基线 JSON 对比")
    parser.add_argument("--root", type=Path, default=Path.cwd(),
                        help="项目根（默认当前目录）")
    args = parser.parse_args(argv)

    project_root = args.root.resolve()

    if args.report:
        return cmd_report(project_root)
    if args.staged:
        return cmd_staged(project_root)
    if args.pretool:
        return cmd_pretool(project_root)
    if args.vs_baseline:
        return cmd_vs_baseline(project_root, args.vs_baseline)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
