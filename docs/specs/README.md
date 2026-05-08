# Executable Specs — 业务规则规约

> **AI 必读**：这里的每个 spec 文件都是业务规则的**单一真相源**。
> 处理业务逻辑前必须 Read 对应 spec，不要凭记忆或推断。

---

## 作用

把口头业务规则**表格化**，防止 AI 每次理解有偏差。
代码可以按 spec 编写，测试可以按 spec 验证。

---

## 使用方式

### 对 AI（Claude / Cursor / 其他）

1. 每次启动会话，**先读这个 README** 获取索引
2. 根据任务，**按需 Read 具体 spec**（不要一次全读）
3. 代码实现时，**严格按 spec 表格执行**，不要自己解释
4. 如果 spec 与用户需求矛盾 → 停下来问用户，然后更新 spec

### 对人类用户

1. 业务规则变化时，**先更新 spec**
2. 通过 commit 信息描述变化原因
3. 每次 AI 问一个业务问题，答案要沉淀到 spec 里

---

## Spec 索引

> 这是占位索引。Fork 本 demo 后，按你项目实际业务流程填写。

| 文件 | 覆盖内容 | 状态 |
|------|---------|------|
| `delete_strategy.md` | 删除分级（A-E 类），哪些表如何删除 | 待建 |
| `<flow_1>.md` | 主业务流程状态机 + 条件分支 | 待建 |
| `<flow_2>.md` | 第二个主业务流程 | 待建 |
| `auth_permissions.md` | 角色 - 权限矩阵（N 角色 × M 权限） | 待建 |
| `audit_requirements.md` | 哪些操作必须审计、哪些豁免 | 待建 |
| `esig_requirements.md` | 哪些操作必须电子签名 | 待建 |
| `notification_rules.md` | 状态变更时的通知对象和时机 | 待建 |

---

## Spec 文件标准格式

每个 spec 必须包含以下章节：

```markdown
# [流程 / 领域名称]

## 目的
一句话说明这个 spec 管什么

## 状态机（如适用）
用表格表达：当前状态 + 允许动作 + 下一状态 + 权限 + 签名要求 + 是否可逆

| 当前状态 | 允许动作 | 下一状态 | 谁能做 | 需要签名？ | 可逆？ |
|---------|---------|---------|-------|----------|-------|
| draft | submit | submitted | 创建者 | 否 | 是 |
| submitted | review | reviewing | reviewer | 否 | 是 |
| reviewing | approve | approved | manager | 是（21 CFR Part 11） | 否 |
| reviewing | reject | draft | manager | 否 | 是 |
| approved | archive | archived | system | 否 | 否 |

## 关键规则
以编号列表形式，每条规则独立可验证：
1. [规则 1]
2. [规则 2]
3. ...

## 例外情况
条件分支、特殊产品类型等

## 字段约定（如适用）
涉及的数据库字段、枚举值、默认值

## 决策历史
- YYYY-MM-DD：[谁]确认[什么规则]，来源[什么反馈]（关联 commit hash 或 session log）
```

---

## 示例：一份完整 spec 长什么样

> 下面是一份示意性的 `complaint_flow.md`（脱敏的占位例子）

```markdown
# 客诉处理流程

## 目的
定义客户投诉从接收到关闭的完整状态流转，含跨部门审批、电子签名要求。

## 状态机

| 当前状态 | 允许动作 | 下一状态 | 谁能做 | 需要签名？ | 可逆？ |
|---------|---------|---------|-------|----------|-------|
| received | assign | investigating | QA manager | 否 | 是 |
| investigating | submit_summary | reviewing | investigator | 是 | 否 |
| reviewing | approve | closed | QA manager | 是 | 否 |
| reviewing | return_for_more_info | investigating | QA manager | 否 | 是 |
| closed | reopen | reviewing | QA manager | 是 | 否 |

## 关键规则

1. 严重等级 = "Critical" 的投诉必须 24 小时内 assign
2. investigation_summary 字段非空才允许 submit_summary
3. closed 状态需双签：investigator + QA manager
4. reopen 操作必须填写 reopen_reason
5. 跨产品线投诉需 cc 给所有产品线的 QA

## 例外情况

- 产品退回类投诉：跳过 investigating，直接进 reviewing（产品线判断）
- 来自监管机构的投诉：必须升级到 director 级别审批

## 字段约定

- `status`：枚举（`received` / `investigating` / `reviewing` / `closed`）
- `severity`：枚举（`low` / `medium` / `high` / `critical`）
- `investigation_summary`：text，submit_summary 后非空校验
- `closed_at`：timestamp，仅 closed 状态非空

## 决策历史

- 2026-01-15：用户确认"严重等级 Critical 必须 24h assign"，来源监管要求 ISO 13485
- 2026-02-03：增加 reopen_reason 必填规则，避免无理由 reopen 留下隐患
- 2026-03-20：跨产品线 cc 规则确认，来源 QA manager 反馈漏通知
```

---

## 更新纪律

Spec 是**活文档**，会随业务演进：

- 用户确认新规则 → **立即更新 spec** + 在决策历史里记录
- 规则变更 → 保留历史（不要直接覆盖），用"废弃于 YYYY-MM-DD"标记
- 每次会话结束，AI 检查本次是否有新业务规则，如有则同步到 spec + session log

---

## Token 优化

每个 spec 独立文件，避免一次性加载全部：

- 做客诉相关 → 只读 `complaint_flow.md`
- 做 QC 相关 → 只读 `qc_flow.md`
- 做删除操作 → 只读 `delete_strategy.md`

Spec 文件保持**小而精**（单个文件 < 10 KB），便于 AI prompt caching。

---

## Spec 与代码的连接

最终目标：spec 里写的状态机能**直接生成**：

1. 后端的状态校验装饰器
2. 前端的按钮可点逻辑
3. 测试用例（每条状态转换都有 test）

当前 demo 阶段：spec 是**人机共读的契约**，AI 在写代码前必须读，写测试时按 spec 矩阵覆盖。

未来增强（视项目阶段）：spec 改成 YAML / JSON，写一次性的 generator，自动生成上面 3 类代码。

---

> Spec 不是文档，是**法律**。
> 业务规则变了就改 spec，再让代码跟上。
> 反过来"代码改了 spec 没改"是协作纪律的失败。
