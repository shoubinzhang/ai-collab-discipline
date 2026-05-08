# Subagents — 多角色 AI 编排

> Claude Code 的 subagent 机制允许把工作分解给不同"角色"的 AI。
> 每个角色有独立的 system prompt、工具白名单、context 窗口。
>
> 三个核心角色刻意分离：**Writer / Reviewer / Tester**。
> 互不信任、互相验证 — 防止单个 AI 既当运动员又当裁判。

---

## 为什么要拆 3 个角色

| 角色 | 倾向 | 单独用的风险 |
|------|------|-------------|
| **Writer** | 求"写出能跑的代码" | 容易忽略边缘情况、容易复用 hack |
| **Reviewer** | 求"挑毛病" | 单独跑会过度挑剔、阻塞进度 |
| **Tester** | 求"覆盖路径" | 单独跑不会主动改代码、只产测试 |

三角色协作 = **写、审、测**三步互锁，谁也不能一人通关。

---

## 工作流

```
用户提需求
    ↓
Writer  ← 写代码（主路径优先，附"未覆盖项"清单）
    ↓
Reviewer ← 审 Writer 的产出（按 5 条禁令、文件规模红线、lessons.md 已知陷阱）
    ↓ 如发现问题，回 Writer 修
    ↓
Tester  ← 写合约测试 + 单元测试，验证 Writer 改动符合 spec
    ↓
用户确认 → 交付
```

---

## 三个角色

| 角色 | 文件 | 主要工具 | 何时调用 |
|------|------|---------|---------|
| **Writer** | [`writer.md`](./writer.md) | Read / Edit / Write / Grep / Bash | 用户确认计划后开始编码 |
| **Reviewer** | [`reviewer.md`](./reviewer.md) | Read / Grep / Bash（只读） | Writer 完成一段改动后 |
| **Tester** | [`tester.md`](./tester.md) | Read / Write / Bash | Reviewer 通过后写测试 |

---

## 调用方式（Claude Code）

### 主 agent 主动调用

```
> 调用 writer agent，按计划改 backend/routers/users.py
```

主 agent 会通过 `Agent` 工具创建 subagent task，subagent 完成后返回结果。

### 主 agent 自动委派

如果你在主对话里说 "review 这段改动"、"写测试"，Claude 会自动选对应 agent。

### 看到一个 PR 怎么验

```
> 用 reviewer agent 审查 PR #123，重点看：
>   - 是否违反 5 条禁令
>   - 是否新增超标文件
>   - 是否漏写测试
```

---

## 编排原则（与本 demo 的纪律对齐）

1. **互不替代**：Writer 不许自己跑测试当通过，Tester 不许动业务代码
2. **证据传递**：每个角色完成后必须在结果里附**已验证 / 未验证**清单
3. **拒绝降级**：任一角色发现做不到时必须回报主 agent，不许擅自精简
4. **读优于写**：所有角色都默认先 Read 再动手

---

## 用户视角的好处

- **审计可追溯**：每个改动可以指给谁是 Writer / 谁审的 / 谁写的测试
- **责任分明**：测试漏了找 Tester，bug 留下找 Reviewer
- **降低单 AI 风险**：单个会话窗口溢出 / 上下文混淆，影响只限当前角色

---

## 调试技巧

如果某个 agent 表现异常：

1. 看它的 `.md` 定义文件，是不是 system prompt 里少写了某条约束
2. 看 `.claude/settings.json` 的 `permissions`，是不是它需要某个工具被 deny 了
3. 看 `Bash` 输出有没有触发 hook 的拦截
