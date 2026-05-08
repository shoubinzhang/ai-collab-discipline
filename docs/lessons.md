# 已知陷阱记录（Lessons Learned）

> 每次新会话开始，AI 必须 Read 本文件。
> 这里记录所有已经踩过的坑，避免重犯。
>
> 本 demo 提取了 **7 个跨项目通用的陷阱模式**（已脱敏，不含真实业务案例）。
> Fork 到自己项目后，请补充自己的真实案例。

---

## 文件格式

每条陷阱包含：

- **触发**：具体发生了什么错误 / 症状
- **根因**：为什么会发生
- **规避**：以后怎么避免
- **验证**：如何确认规避措施生效
- **发现日期**：什么时候被记录进来

---

## Lesson 1: React Hook 顺序错误

- **触发**：某个 tab 切换时页面崩溃
  - 报错：`Minified React error #310` — "Rendered fewer hooks than expected"
- **根因**：`useMemo` / `useEffect` 被放在 `if (loading) return ...` 之后，违反 React Rules of Hooks
  - 首次渲染：`loading=true` → early return，跳过 hook
  - 二次渲染：`loading=false` → 执行到 hook，hook 数量变化，React 崩溃
- **规避**：
  - 所有 hooks（`useState` / `useMemo` / `useEffect` / `useCallback` / `useRef`）**必须**在任何条件 `return` 之前调用
  - 模式：先声明所有 hook → 再做条件渲染判断
- **验证**：
  - 每次写包含 early return 的组件，肉眼从上到下检查 hook 位置
  - **Build 通过不代表 hook 顺序正确**（运行时才报错）
  - 必须真实切 tab 测试
- **类型**：前端 / React
- **发现日期**：（填写你项目实际日期）

---

## Lesson 2: HTTP client 已自动解包 response.data

- **触发**：某仪表盘数据空白，不报错但无数据
- **根因**：HTTP client 的 axios interceptor 已经返回了 `response.data`，前端再写 `res.data.xxx` 拿到 `undefined`
- **规避**：
  - 使用 client.get / post / put / delete 时，返回值 `res` **本身就是 data**
  - 不要再写 `res.data.xxx`，直接写 `res.xxx`
- **验证**：
  - 新写 API 调用时，先 Read 其他页面的类似用法
  - Grep 潜在误用：`apiClient\.\w+.*\.data\.`
- **类型**：前端 / API
- **发现日期**：（填写你项目实际日期）

---

## Lesson 3: PostgreSQL ALTER TABLE ADD CONSTRAINT 不支持 IF NOT EXISTS

- **触发**：执行 `ALTER TABLE x ADD CONSTRAINT IF NOT EXISTS uq_x UNIQUE (col);` 报语法错误
- **根因**：PostgreSQL 的 `ADD CONSTRAINT` 语法**不支持** `IF NOT EXISTS`
- **规避**：用 `DO $$ ... END $$` 块包装：
  ```sql
  DO $$
  BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_x') THEN
      ALTER TABLE x ADD CONSTRAINT uq_x UNIQUE (col);
    END IF;
  END $$;
  ```
- **注意**：`ADD COLUMN IF NOT EXISTS` 和 `CREATE INDEX IF NOT EXISTS` 是支持的，**只有 `ADD CONSTRAINT` 不支持**
- **验证**：部署 SQL 前在开发机跑一遍
- **类型**：数据库 / PostgreSQL
- **发现日期**：（填写你项目实际日期）

---

## Lesson 4: DB Schema 与代码不同步

- **触发**：API `POST /xxx/submit` 返回 500 错误
  - 报错：`字段 "investigation_summary" 不存在`
  - 前端可能误显示成 CORS 错误（500 响应没 CORS 头）
- **根因**：代码改了依赖新列的 UPDATE 语句，但 DB 没加列
- **规避**：
  - 任何涉及新字段的代码改动，**改代码前**先验证 DB 真实 schema：
    ```python
    from sqlalchemy import inspect
    inspect(engine).get_columns('table_name')
    ```
  - 如果列不存在，**先**给出迁移 / `ALTER TABLE` 让用户执行
  - **然后**再改代码
- **注意**：500 错误在前端常表现为 CORS 错误（错误响应没有 CORS 头），不要被误导
- **验证**：每次涉及 INSERT / UPDATE 新字段时强制走一遍 schema 检查
- **类型**：数据库 / 部署
- **发现日期**：（填写你项目实际日期）

---

## Lesson 5: Agent 生成代码必须人工审查

- **触发**：Subagent 写了一个组件，build 通过，但运行时报 hook 顺序错（见 Lesson 1）
- **根因**：Subagent 写完只看 build，没人工 review；build 通过 ≠ 运行正确
- **规避**：
  - Agent 写代码后**必须**：
    1. 人工 Grep 关键变更点（hooks、状态变化、DB 调用）
    2. **Build 通过只是最低门槛，不是正确性证明**
    3. 对 React 组件特别关注 hook 顺序、early return、副作用清理
    4. 后端组件特别关注 DB 字段、权限装饰器、事务边界
  - 同时跑多个 agent 写代码时，**并行度不超过 2**（读取 agent 可更多）
- **验证**：每次 agent 完成后至少 Read 一次关键文件的改动点
- **类型**：AI 协作 / 流程
- **发现日期**：（填写你项目实际日期）

---

## Lesson 6: Migration Revision ID 重复导致循环

- **触发**：`alembic upgrade head` 报 `CycleDetected`，进程无法启动
- **根因**：不同日期的 migration 复用了相同的 revision ID（手写 ID 时撞了）
- **规避**：
  - 新建 migration 时，revision ID 必须**全局唯一**
  - 推荐使用工具自动生成 hash（不要手写看起来"随意"的 ID）
  - 命名检查：每次新增 migration 前跑 `alembic heads` 确认无冲突
- **验证**：CI 门禁加入 alembic 链条验证
- **类型**：数据库 / 迁移
- **发现日期**：（填写你项目实际日期）

---

## Lesson 7: Python 函数内赋值遮蔽全局导入

- **触发**：API 报 `UnboundLocalError: cannot access local variable 'text' where it is not associated with a value`
- **根因**：文件顶层 `from sqlalchemy import text`，但函数内有 `text = ''.join(...)`
  - Python 编译期把函数内所有 `text` 都绑定为局部变量
  - 导致先执行到 `text("""SELECT ...""")` 时（早于赋值）报 `UnboundLocal`
- **规避**：
  - 不要用常见 import 名（`text` / `io` / `time` / `json` / `dict` / `list` / `type`）做函数内局部变量
  - 改名：用 `p_text` / `raw_text` / `text_val` 等
- **验证**：python 语法编译能过（`py_compile`）**不代表运行 OK**；必须真实调用函数
- **类型**：后端 / Python 陷阱
- **发现日期**：（填写你项目实际日期）

---

## 🚨 元陷阱：巨型文件失控

- **触发**：外部审查揭露多个文件突破 1500 行 / 2000 行 / 3000 行
- **根因**：
  1. 项目规则**零**文件行数约束
  2. 每次 AI 会话独立，加新功能路径最短 = 往最近的文件堆，N 次会话累计成 3000 行
  3. 无 pre-commit / CI 门禁拦截
  4. 审查机制自身漏洞 — 总是关注"功能是否对"，没关注"文件是否在限内"
- **规避**：
  1. CLAUDE.md 写「文件规模红线」章节（本 demo 已写）
  2. **改任何文件前必须 `wc -l`** → 超警戒线告知用户、超硬上限拒绝加新功能
  3. **修改超标文件必须同次拆分至少一个子组件**，原文件行数必须减少
  4. CI 跑 `check_file_size_limits.py`，新增超标 PR 直接 fail
- **验证**：
  ```bash
  python3 scripts/ci/check_file_size_limits.py --report
  python3 scripts/ci/check_file_size_limits.py --staged   # PR 时
  ```
- **类型**：AI 协作 / 流程
- **发现日期**：（填写你项目实际日期）

---

## 🚨 元陷阱：AI 擅自降级用户要求

- **触发**：用户要 9 份详细文档，AI 因 context 压力大没请示，把 8 份写成精简版（行数减半）
- **根因**：AI 训练时被鼓励"在限制下尽力完成"，导致默认行为是**降级而非请示**
  - 用户视角：以为得到 9 份详细文档，实际只有 1 份达标
  - AI 视角：自认为是"务实变通"，但本质是说谎
- **规避**：
  1. CLAUDE.md 写「禁令 4：禁止对用户指令做任何降级处理」
  2. AI 改完必须给**证据格式的报告**（已改 / 已验证 / 未验证 / 潜在影响）
  3. 降级前**必须请示**，被迫降级要在代码 / 文档里标 `# TODO: 原要求 X 当前降级为 Y`
- **验证**：
  - 每次设计文档：行数应在原要求范围内（手测 `wc -l docs/design/*.md`）
  - 每次会话结束：交付物清单是否与计划清单一一对应
- **类型**：AI 协作 / 流程
- **发现日期**：（填写你项目实际日期）

---

## 如何使用本文件

### Fork 这个 demo 后

1. 上面 7 + 2 个 lesson 是**通用陷阱**，留着即可（其他类似项目大概率会遇到）
2. **新项目自己踩到的坑**追加在文件末尾，按同样格式
3. 删除"（填写你项目实际日期）"占位

### 添加新陷阱的格式

```markdown
## Lesson N+1: [简短标题]

- **触发**：[症状]
- **根因**：[为什么]
- **规避**：[怎么做]
- **验证**：[怎么确认]
- **类型**：[前端/后端/数据库/部署/AI 协作]
- **发现日期**：YYYY-MM-DD
- **相关 commit**：（可选）
```

### 与会话日志的关系

- **新踩的坑** → 写入 lessons.md（永久保留）
- **临时事件** → 写入 session_logs/（按日期组织）
- **业务规则确认** → 写入 specs/（结构化规约）

每次会话结束，AI 必须主动检查：本次有没有新踩的坑？有就更新 lessons.md。

---

> 这个文件是**对 AI 的备忘录**。
> 每次会话开新窗口、上下文重置，但 lessons.md 永远在那里 —— 这是项目的"长期记忆"。
