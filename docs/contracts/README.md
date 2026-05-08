# Contracts — API 契约冻结（L5 代码契约层）

> **目的**：API 响应结构一旦发布给前端 / 客户端，就**冻结**。
> 改字段必须同步改契约 + 改测试 + 升版本号 — 否则 CI fail。
>
> 这是 L5「代码契约层」的核心：**合约测试 + JSON Schema 双保险**。

---

## 为什么要冻结

最常见的失败模式：

1. 后端工程师认为 `user_name` 改成 `username` 是"小修复"
2. 提交合并，部署到生产
3. 前端 5 分钟后挂掉 — 因为某处 `res.user_name` 突然变成 `undefined`
4. 用户报告 bug，回追到那次"小修复"，但已经 1 周后了

**根本问题**：API 响应字段是**跨服务的隐式契约**，但通常不被当作契约对待。

---

## 双保险机制

### 保险 1：JSON Schema 锁定结构

每个稳定的 API 端点配一个 schema 文件：

```
docs/contracts/
├── README.md
├── schemas/
│   ├── v1/
│   │   ├── auth_login_response.schema.json
│   │   ├── complaint_get_response.schema.json
│   │   └── ...
│   └── v2/
│       └── ...
└── baselines/
    ├── auth_login.example.json          # 真实响应快照
    ├── complaint_get.example.json
    └── ...
```

JSON Schema 描述结构（字段名、类型、必需性）；baseline 是真实响应样本。

### 保险 2：合约测试

写在 `tests/contracts/` 下，**不验业务逻辑**，只验响应结构：

```python
# tests/contracts/test_auth_contract.py
import json
from pathlib import Path
from jsonschema import validate

SCHEMA_DIR = Path(__file__).parent.parent.parent / "docs/contracts/schemas/v1"

def test_login_response_matches_schema(test_client):
    response = test_client.post("/api/auth/login", json={
        "username": "test",
        "password": "test"
    })
    assert response.status_code == 200

    schema = json.loads((SCHEMA_DIR / "auth_login_response.schema.json").read_text())
    validate(instance=response.json(), schema=schema)
```

### 保险 3（推荐）：Baseline diff

每次发版前跑一次"真实请求 → 实际响应 → 对比 baseline"：

```bash
python3 scripts/ci/check_contract_drift.py --baseline docs/contracts/baselines/
```

如果实际响应字段比 baseline 多/少 → CI fail，强制开发者解释。

---

## 工作流

### 新增端点

1. 实现端点
2. 跑一次拿真实响应
3. 把响应保存为 `baselines/<endpoint>.example.json`
4. 用工具（如 [quicktype](https://quicktype.io)）生成 schema → `schemas/v1/<endpoint>_response.schema.json`
5. 写合约测试 → `tests/contracts/test_<endpoint>_contract.py`
6. 提交 PR

### 修改字段（高风险）

1. **先讨论**：用户确认要改吗？为什么？
2. 决定版本策略：
   - **新版本**（v1 → v2）：保留 v1，新建 v2 schema，前端逐步迁移
   - **就地改 v1**（不推荐，仅限内部 API）：改 schema + 改 baseline + 改测试 + 通知所有 consumer
3. 改 schema → 改 baseline → 改测试 → 改后端代码
4. 跑 `check_contract_drift.py` 验证
5. PR 描述里**必须**说明字段变化和迁移计划

### 删除字段（最高风险）

- 至少经过 1 个版本的 deprecated 期（schema 标 `deprecated: true`）
- 通知所有已知 consumer（前端 / 第三方）
- 监控字段使用，确认 0 调用后才能删

---

## 与 specs 的关系

| 文档 | 描述 | 谁是真相源 |
|------|------|-----------|
| `docs/specs/*.md` | 业务规则（状态机、权限、流程） | 业务 |
| `docs/contracts/schemas/` | API 响应**结构** | 技术 |
| `docs/contracts/baselines/` | API 响应**样本** | 实际部署 |

业务规则可以变（spec 可以改），但响应结构改动需要更高的纪律（必须升版本 / deprecated / 通知）。

---

## CI 集成

`scripts/ci/check_contract_drift.py`（在 `scripts/ci/` 下）会：

1. 起后端服务
2. 用预设的请求 hit 每个端点
3. 把响应与 baseline 比对
4. 任何字段不一致（增 / 减 / 改类型）→ 退出码非 0 → CI fail

每个 PR 都跑一次，确保契约不漂移。

---

## 占位文件结构

> Fork 到你项目后，按下面结构创建：

```
docs/contracts/
├── README.md                                    # 本文件
├── schemas/
│   ├── v1/
│   │   └── (按端点一个 .schema.json)
│   └── v2/                                       # 升版本时新建
│       └── ...
└── baselines/
    └── (按端点一个 .example.json)

tests/contracts/
├── conftest.py                                   # 测试 fixture
├── test_auth_contract.py                         # 一个端点一个测试
└── ...
```

---

## 何时**不**需要契约

不是所有端点都值得做契约：

✅ **必须做**：
- 跨服务调用（前端 → 后端，A 服务 → B 服务）
- 第三方 API（外部 consumer）
- 正在被多个团队消费的端点

⚠️ **可不做**：
- 内部脚本调用（一次性）
- 调试 / 监控端点（响应结构不稳定）
- 仅供开发者用的 API（如 `/admin/debug/*`）

判断标准：**如果改这个端点会让其他人挂，就值得做契约**。

---

## 实践建议

1. **从核心端点开始**：先把 5-10 个关键端点（登录、用户、主业务流程）锁死，再逐步铺开
2. **schema 用宽松起点**：先 `additionalProperties: true`，发现问题再收紧
3. **baseline 自动化**：写脚本一键采样，避免手动复制粘贴
4. **错误响应也要锁**：成功响应锁了，但 422/403/500 的结构也要稳定
5. **版本号写到 URL 或 Header**：方便 v1/v2 共存

---

> 契约是**对未来的承诺**。
> 一旦你说"这个端点的响应是这样"，就要负责让它一直这样。
> 否则，跨服务协作就是一场永久的猜谜游戏。
