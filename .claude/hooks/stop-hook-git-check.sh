#!/usr/bin/env bash
# Stop hook — AI 每轮结束时检查未提交改动
#
# 触发：Claude Code Stop event（每次 AI 回合结束）
# 目的：避免 AI 改完代码忘 commit / push，导致下次会话上下文丢失
#
# 退出码：
#   0 — 工作区干净 / 用户自己处理
#   非 0 — 有未提交改动，提示 AI 处理
#
# 行为：
#   - 干净：静默退出
#   - 有 untracked / modified：打印 git status 摘要，退出码 0（不阻塞，但会打到 Claude 的 stdout）
#
# 不强制 fail（exit 1）的原因：
#   - 有时改完代码 AI 在写文档准备 commit，强 fail 反而打断流程
#   - 改成提示让 AI 看到、自行决定何时 commit

set -uo pipefail

# 仅在 git 仓库内运行
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  exit 0
fi

# 检查未跟踪 / 已修改文件数
modified_count=$(git status --porcelain 2>/dev/null | wc -l)

if [ "$modified_count" -eq 0 ]; then
  # 工作区干净 — 静默
  exit 0
fi

# 有改动 — 打印摘要
echo ""
echo "[stop-hook] 检测到 ${modified_count} 个未提交改动："
git status --short 2>/dev/null | head -20
if [ "$modified_count" -gt 20 ]; then
  echo "  ... 还有 $((modified_count - 20)) 个未列出"
fi
echo ""
echo "[stop-hook] 提示：完成本轮工作前请考虑 commit 这些改动，或显式告诉用户为什么暂不 commit。"
echo "           （Claude Code 在 stop 事件后默认提示，不强制 fail）"

# 不阻塞，正常退出
exit 0
