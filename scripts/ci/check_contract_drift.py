#!/usr/bin/env python3
"""
check_contract_drift.py · API 契约漂移检测（L4 CI 门禁层）

"契约漂移" 定义：API 实际响应的字段集与 baseline 不一致。
即使响应仍然合法 JSON、状态码 200，字段增删/重命名/类型变化都视为漂移。

使用方式：
    # 仅做 schema vs baseline 一致性检查（离线、CI 默认）
    python3 scripts/ci/check_contract_drift.py --offline

    # 起一个本地后端，hit 每个端点对比 baseline（部署前用）
    python3 scripts/ci/check_contract_drift.py --live --base-url http://localhost:8000

    # 用样例配置生成 baseline / schema 骨架（首次接入）
    python3 scripts/ci/check_contract_drift.py --bootstrap --endpoint /api/health

退出码：
    0 — 无漂移
    1 — 检测到漂移（CI 应 fail）
    2 — 配置缺失 / 文件错误

依赖：仅 Python stdlib + 可选 jsonschema（如装了用、没装则降级到字段集对比）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib import request as urlrequest, error as urlerror


# ─────────────────────────────────────────────────────────────────────────────
# 配置 — 接入你项目时改这里
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_CONTRACTS_DIR = Path("docs/contracts")
DEFAULT_TIMEOUT_SECONDS = 10


# ─────────────────────────────────────────────────────────────────────────────
# 字段集提取 — 用于"非 jsonschema"环境下的轻量对比
# ─────────────────────────────────────────────────────────────────────────────

def extract_field_set(obj: Any, prefix: str = "") -> set[str]:
    """
    递归提取 JSON 中的"字段路径集合"。
    例：{"user": {"id": 1, "name": "x"}, "tags": [{"k": "v"}]}
        → {"user", "user.id", "user.name", "tags[]", "tags[].k"}

    用于检测字段被增 / 删 / 改名。值的变化不会触发漂移。
    """
    fields: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            fields.add(path)
            fields.update(extract_field_set(v, path))
    elif isinstance(obj, list):
        # 数组元素的字段统一汇总（不区分位置）
        for item in obj:
            fields.update(extract_field_set(item, f"{prefix}[]"))
    # 标量不增加路径
    return fields


def diff_field_sets(baseline: set[str], current: set[str]) -> tuple[set[str], set[str]]:
    """返回 (新增的字段, 缺失的字段)。"""
    added = current - baseline
    removed = baseline - current
    return added, removed


# ─────────────────────────────────────────────────────────────────────────────
# Schema 验证（如装了 jsonschema 库）
# ─────────────────────────────────────────────────────────────────────────────

try:
    from jsonschema import validate as _jsonschema_validate
    from jsonschema import ValidationError as _ValidationError
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


def validate_against_schema(payload: Any, schema: dict) -> str | None:
    """返回 None 表示通过，否则返回错误描述。"""
    if not HAS_JSONSCHEMA:
        return "jsonschema 库未安装，跳过 schema 校验（仅做字段集对比）"
    try:
        _jsonschema_validate(instance=payload, schema=schema)
        return None
    except _ValidationError as e:  # type: ignore[misc]
        return f"{e.message} @ {'/'.join(str(p) for p in e.absolute_path)}"


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint 配置加载
# ─────────────────────────────────────────────────────────────────────────────

def load_endpoint_config(contracts_dir: Path) -> list[dict]:
    """
    读取 contracts_dir/endpoints.json（用户维护的端点清单）。
    格式见底部 BOOTSTRAP_ENDPOINTS_TEMPLATE。
    """
    cfg = contracts_dir / "endpoints.json"
    if not cfg.exists():
        print(f"❌ 配置文件不存在：{cfg}", file=sys.stderr)
        print("   运行 --bootstrap --endpoint /your/path 生成模板", file=sys.stderr)
        return []
    return json.loads(cfg.read_text())


def load_baseline(contracts_dir: Path, endpoint_id: str) -> dict | None:
    f = contracts_dir / "baselines" / f"{endpoint_id}.example.json"
    if not f.exists():
        return None
    return json.loads(f.read_text())


def load_schema(contracts_dir: Path, endpoint_id: str, version: str = "v1") -> dict | None:
    f = contracts_dir / "schemas" / version / f"{endpoint_id}.schema.json"
    if not f.exists():
        return None
    return json.loads(f.read_text())


# ─────────────────────────────────────────────────────────────────────────────
# 模式 1：离线检查（schema vs baseline 一致性）
# ─────────────────────────────────────────────────────────────────────────────

def cmd_offline(contracts_dir: Path) -> int:
    """检查每个 baseline 是否符合自己的 schema（不发任何网络请求）。"""
    endpoints = load_endpoint_config(contracts_dir)
    if not endpoints:
        return 2

    drift_found = False
    print(f"📊 离线契约一致性检查（{len(endpoints)} 个端点）\n")

    for ep in endpoints:
        eid = ep["id"]
        version = ep.get("version", "v1")
        baseline = load_baseline(contracts_dir, eid)
        schema = load_schema(contracts_dir, eid, version)

        if baseline is None:
            print(f"  ⚠️  {eid:30} baseline 缺失")
            drift_found = True
            continue
        if schema is None:
            print(f"  ⚠️  {eid:30} schema 缺失")
            drift_found = True
            continue

        err = validate_against_schema(baseline, schema)
        if err is None:
            print(f"  ✅ {eid:30} baseline 符合 schema")
        elif "未安装" in (err or ""):
            print(f"  ℹ️  {eid:30} {err}")
        else:
            print(f"  🚨 {eid:30} 不符合 schema：{err}")
            drift_found = True

    if drift_found:
        print("\n🚨 检测到契约定义不一致 — CI 失败")
        return 1
    print("\n✅ 全部端点的 baseline 与 schema 一致")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# 模式 2：在线检查（hit live API，对比 baseline 字段集）
# ─────────────────────────────────────────────────────────────────────────────

def fetch_live(url: str, method: str, headers: dict, body: Any,
               timeout: int) -> tuple[int, Any]:
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urlrequest.Request(url, data=data, method=method, headers=headers)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
            return resp.status, payload
    except urlerror.HTTPError as e:
        try:
            payload = json.loads(e.read().decode("utf-8"))
        except Exception:
            payload = {"_error": str(e)}
        return e.code, payload
    except Exception as e:
        return 0, {"_error": str(e)}


def cmd_live(contracts_dir: Path, base_url: str, timeout: int) -> int:
    """对每个端点发请求，把响应字段集与 baseline 对比。"""
    endpoints = load_endpoint_config(contracts_dir)
    if not endpoints:
        return 2

    drift_found = False
    print(f"📊 在线契约漂移检查 · {base_url}（{len(endpoints)} 个端点）\n")

    for ep in endpoints:
        eid = ep["id"]
        method = ep.get("method", "GET")
        path = ep["path"]
        url = base_url.rstrip("/") + path
        headers = ep.get("headers", {"Content-Type": "application/json"})
        body = ep.get("request_body")

        baseline = load_baseline(contracts_dir, eid)
        if baseline is None:
            print(f"  ⚠️  {eid:30} baseline 缺失，跳过")
            continue

        status, actual = fetch_live(url, method, headers, body, timeout)
        expected_status = ep.get("expected_status", 200)

        if status != expected_status:
            print(f"  🚨 {eid:30} 状态码 {status}（期望 {expected_status}）")
            drift_found = True
            continue

        added, removed = diff_field_sets(
            extract_field_set(baseline),
            extract_field_set(actual),
        )

        if not added and not removed:
            print(f"  ✅ {eid:30} 无漂移")
        else:
            print(f"  🚨 {eid:30} 检测到字段漂移：")
            if added:
                print(f"     新增字段：{sorted(added)}")
            if removed:
                print(f"     缺失字段：{sorted(removed)}")
            drift_found = True

    if drift_found:
        print("\n🚨 契约漂移 — 修字段必须同步改 baseline + schema + 升版本号")
        return 1
    print("\n✅ 无漂移")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# 模式 3：bootstrap（生成模板）
# ─────────────────────────────────────────────────────────────────────────────

BOOTSTRAP_ENDPOINTS_TEMPLATE = """[
  {
    "id": "auth_login",
    "path": "/api/auth/login",
    "method": "POST",
    "request_body": {"username": "test", "password": "test"},
    "expected_status": 200,
    "version": "v1"
  },
  {
    "id": "health_check",
    "path": "/api/health",
    "method": "GET",
    "expected_status": 200,
    "version": "v1"
  }
]
"""

BOOTSTRAP_BASELINE_TEMPLATE = """{
  "_comment": "把真实 API 响应粘进来，作为契约 baseline。任何字段变动都会被 CI 检测到。",
  "status": "ok",
  "user": {
    "id": 1,
    "username": "example"
  },
  "token": "..."
}
"""

BOOTSTRAP_SCHEMA_TEMPLATE = """{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["status"],
  "additionalProperties": true,
  "properties": {
    "status": {"type": "string"}
  }
}
"""

def cmd_bootstrap(contracts_dir: Path, endpoint_id: str) -> int:
    (contracts_dir / "schemas" / "v1").mkdir(parents=True, exist_ok=True)
    (contracts_dir / "baselines").mkdir(parents=True, exist_ok=True)

    cfg = contracts_dir / "endpoints.json"
    if not cfg.exists():
        cfg.write_text(BOOTSTRAP_ENDPOINTS_TEMPLATE)
        print(f"✅ 生成 {cfg}")

    baseline_f = contracts_dir / "baselines" / f"{endpoint_id}.example.json"
    if not baseline_f.exists():
        baseline_f.write_text(BOOTSTRAP_BASELINE_TEMPLATE)
        print(f"✅ 生成 {baseline_f}")

    schema_f = contracts_dir / "schemas" / "v1" / f"{endpoint_id}.schema.json"
    if not schema_f.exists():
        schema_f.write_text(BOOTSTRAP_SCHEMA_TEMPLATE)
        print(f"✅ 生成 {schema_f}")

    print(f"\n下一步：把真实 API 响应写入 {baseline_f}，调整 {schema_f} 描述结构。")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--offline", action="store_true",
                       help="离线检查：baseline 是否符合 schema")
    group.add_argument("--live", action="store_true",
                       help="在线检查：hit live API 对比 baseline")
    group.add_argument("--bootstrap", action="store_true",
                       help="生成 endpoints.json / baseline / schema 模板")
    parser.add_argument("--contracts-dir", type=Path, default=DEFAULT_CONTRACTS_DIR,
                       help=f"契约目录（默认 {DEFAULT_CONTRACTS_DIR}）")
    parser.add_argument("--base-url", default="http://localhost:8000",
                       help="--live 模式的目标 base URL")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS,
                       help="HTTP 超时（秒）")
    parser.add_argument("--endpoint", default="auth_login",
                       help="--bootstrap 模式的端点 id")
    args = parser.parse_args(argv)

    contracts_dir: Path = args.contracts_dir.resolve() if args.contracts_dir.is_absolute() \
        else (Path.cwd() / args.contracts_dir)

    if args.offline:
        return cmd_offline(contracts_dir)
    if args.live:
        return cmd_live(contracts_dir, args.base_url, args.timeout)
    if args.bootstrap:
        return cmd_bootstrap(contracts_dir, args.endpoint)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
