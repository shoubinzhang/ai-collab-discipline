"""
register_middleware.py · L6 运行时层 · 7 层中间件注册（FastAPI 骨架）

设计理念
========
"中间件栈" 是 L6 运行时层的核心 — 把横切关注点（cross-cutting concerns）从业务代码里抽出，
保证每个请求都被同一套规则处理：审计 / 认证 / 幂等 / 安全 / 限流 / 防护 / 性能。

为什么必须 7 层而不是 1 层 "做完所有事"
======================================
1. **职责分离**：每层只做一件事，方便单独替换 / 测试
2. **顺序敏感**：审计在最外（要看到所有请求）；认证在外（防越权）；性能在最里（量准）
3. **失败隔离**：限流 / 防护层可独立熔断不影响其他层
4. **合规性**：GMP / 21 CFR Part 11 / ISO 13485 都要求审计追踪不可绕过

注册顺序（从外到内）
=====================
请求进入 →
  [1] AuditMiddleware           最外层，记录所有请求的元数据
  [2] AuthMiddleware            JWT / Session 验证、注入 user 上下文
  [3] IdempotencyMiddleware     幂等 key 检查（防重复提交）
  [4] SecurityHeadersMiddleware CSP / HSTS / X-Frame-Options / nosniff
  [5] RateLimitMiddleware       限流（per-user / per-IP / per-endpoint）
  [6] InputSanitizerMiddleware  XSS / SQL 注入 / 文件路径穿越防护
  [7] PerformanceMiddleware     最内层，精确量响应时间
                                ↓
                              业务路由
                                ↓
响应返回 ←  反向穿过 7 层

注意：FastAPI / Starlette 的 add_middleware 顺序是**后注册先执行**（栈），
所以下面 add_middleware 的代码顺序是反过来的。

——————————————————————————————————————————————————————————————————————————————
本文件是骨架，包含完整设计意图但不含具体实现。
Fork 后请按你项目实际填充每个 middleware 的 dispatch 方法。
"""
from __future__ import annotations

# 在真实项目里用：
# from fastapi import FastAPI
# from starlette.middleware.base import BaseHTTPMiddleware
# from starlette.middleware.cors import CORSMiddleware
# from starlette.requests import Request
# from starlette.responses import Response

# 为了 demo 可独立 py_compile，使用占位 stub
class FastAPI:
    def add_middleware(self, *args, **kwargs):
        """占位。真实项目用 starlette 的 add_middleware。"""
        pass

class BaseHTTPMiddleware:
    """占位基类。真实项目从 starlette.middleware.base 导入。"""
    def __init__(self, app, **kwargs):
        self.app = app


# ─────────────────────────────────────────────────────────────────────────────
# Middleware 1：AuditMiddleware（最外层）
# ─────────────────────────────────────────────────────────────────────────────

class AuditMiddleware(BaseHTTPMiddleware):
    """
    审计追踪 — 记录所有写操作（POST / PUT / DELETE / PATCH）。

    必须满足（GMP ALCOA+ / 21 CFR Part 11）：
    - Attributable    每条记录关联到具体用户
    - Legible         明文 + 结构化（JSON），不要二进制
    - Contemporaneous 操作发生时即时记录，不能后补
    - Original        原始数据，不可改写（用 SHA256 校验）
    - Accurate        精确到毫秒、含请求体 + 响应状态

    实现要点：
    - 写入异步队列，不阻塞请求
    - 记录后给每条加 SHA256 校验（防篡改）
    - 失败时降级写本地文件，不能因审计挂掉业务
    - retention_expires_at 字段管理保留期（按 SOP 通常 ≥ 7 年）
    """

    async def dispatch(self, request, call_next):
        # TODO: 在此填充审计逻辑
        # 1. 提取 request 元数据（method, path, user_id, ip, timestamp）
        # 2. 读取 request body（注意 stream 一次性消费问题）
        # 3. 调用 call_next(request) 拿响应
        # 4. 记录响应状态码 + 关键字段
        # 5. 异步入库（global_audit_logs 表）
        # 6. 失败时写本地 JSONL 文件作为兜底
        return await call_next(request)


# ─────────────────────────────────────────────────────────────────────────────
# Middleware 2：AuthMiddleware
# ─────────────────────────────────────────────────────────────────────────────

class AuthMiddleware(BaseHTTPMiddleware):
    """
    JWT / Session 验证 + 用户上下文注入。

    设计要点：
    - token_version 机制：用户改密码 / 注销时增 version，旧 token 立刻失效
    - 黑名单：Redis 存被注销的 jti，30 分钟有效期
    - 公开路由白名单：/health, /docs, /api/auth/login 等
    - 失败响应：401 + 明确 reason（expired / invalid / blacklisted）

    注意：本中间件不做权限判断（那是 RBAC 装饰器的事），只做"是不是合法用户"。
    """

    PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/api/auth/login"}

    async def dispatch(self, request, call_next):
        # TODO:
        # 1. 提取 Authorization Header / Cookie
        # 2. 公开路由直接 pass
        # 3. 解析 JWT，校验签名 / 过期 / token_version
        # 4. 检查 Redis 黑名单
        # 5. 把 user 注入 request.state.user
        # 6. 失败返回 401
        return await call_next(request)


# ─────────────────────────────────────────────────────────────────────────────
# Middleware 3：IdempotencyMiddleware
# ─────────────────────────────────────────────────────────────────────────────

class IdempotencyMiddleware(BaseHTTPMiddleware):
    """
    幂等性 — 防止重复提交导致重复创建 / 重复扣库存 / 重复发邮件。

    机制：
    - 客户端在 Header 里带 Idempotency-Key（UUID）
    - 服务端缓存 (key, response) 5 分钟
    - 同一 key 第二次提交，直接返回上次的响应

    适用范围：
    - 必须做：POST / PUT / DELETE 写操作
    - 不需要：GET / HEAD（本身幂等）
    - 不要做：流式响应、文件下载

    陷阱：
    - 不要用 request body hash 当 key（同样数据可能合法重复）
    - 不要在 key 里编码用户信息（重放攻击风险）
    """

    async def dispatch(self, request, call_next):
        # TODO:
        # 1. 跳过 GET / HEAD
        # 2. 读 Idempotency-Key Header
        # 3. 查 Redis 缓存
        # 4. 命中：直接返回缓存的响应
        # 5. 未命中：调用 call_next，把响应缓存入 Redis（5 分钟）
        return await call_next(request)


# ─────────────────────────────────────────────────────────────────────────────
# Middleware 4：SecurityHeadersMiddleware
# ─────────────────────────────────────────────────────────────────────────────

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    安全响应头 — OWASP 推荐套装。

    Headers：
    - Content-Security-Policy: 限制资源加载来源
    - X-Frame-Options: DENY                防 iframe 嵌套（点击劫持）
    - X-Content-Type-Options: nosniff      防 MIME 嗅探
    - Strict-Transport-Security: ...       强制 HTTPS（生产）
    - Referrer-Policy: strict-origin-when-cross-origin
    - Permissions-Policy: ...              限制浏览器 API 访问

    陷阱：
    - CSP 太严格会打挂前端，先 Report-Only 再 enforce
    - HSTS 在内网部署时关掉（会强制走 HTTPS 但内网可能没证书）
    """

    SECURITY_HEADERS = {
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        # 按你项目实际填写：
        # "Content-Security-Policy": "default-src 'self'; ...",
        # "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    }

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        # TODO: 把 SECURITY_HEADERS 加到 response.headers
        return response


# ─────────────────────────────────────────────────────────────────────────────
# Middleware 5：RateLimitMiddleware
# ─────────────────────────────────────────────────────────────────────────────

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    限流 — 基于 Redis 滑动窗口。

    策略（按端点配置）：
    - /api/auth/login   : 5 次 / 5 分钟（防爆破）
    - /api/upload/*     : 30 次 / 分钟（防滥用）
    - 其他              : 100 次 / 分钟（默认保护）

    维度：
    - 默认按 user_id（已认证）+ IP（未认证）混合
    - 高敏感操作按 user_id + endpoint 双维度

    降级：
    - Redis 不可用时降级到内存限流（per-process）
    - 完全不可用时 fail open（让请求过，记日志）

    返回：
    - 429 Too Many Requests
    - Retry-After: <seconds>
    - X-RateLimit-Remaining: <N>
    """

    async def dispatch(self, request, call_next):
        # TODO:
        # 1. 计算限流维度 key（user/ip/endpoint）
        # 2. Redis INCR + EXPIRE
        # 3. 超限返回 429
        return await call_next(request)


# ─────────────────────────────────────────────────────────────────────────────
# Middleware 6：InputSanitizerMiddleware
# ─────────────────────────────────────────────────────────────────────────────

class InputSanitizerMiddleware(BaseHTTPMiddleware):
    """
    输入消毒 — XSS / SQL 注入 / 路径穿越的最后防线。

    检查：
    - Query string / Path / Body 里的 <script> / javascript: / data: 等
    - SQL 注入特征：单引号 + OR + = / UNION SELECT / DROP TABLE
    - 路径穿越：../ / ..%2F / 绝对路径
    - 巨型 payload：限制 body 大小（避免 OOM）

    哲学：
    - 这是**深度防御**层 — 业务代码里也要做参数化查询 / 转义，不要依赖此层
    - 此层主要兜底"被忽略的输入点"

    陷阱：
    - 不要"消毒"业务数据（如 markdown 字段）—— 那是 escape 在输出端做
    - 仅检测明显恶意 pattern；模糊匹配会误伤正常文本
    """

    async def dispatch(self, request, call_next):
        # TODO: 检测可疑 pattern，记录可疑请求 → 返回 400
        return await call_next(request)


# ─────────────────────────────────────────────────────────────────────────────
# Middleware 7：PerformanceMiddleware（最内层）
# ─────────────────────────────────────────────────────────────────────────────

class PerformanceMiddleware(BaseHTTPMiddleware):
    """
    性能计时 — 记录每个请求的响应时间。

    测量：
    - start_time 在最内层（最接近真实业务）
    - 写到 response header（X-Process-Time）方便前端调试
    - 慢请求（> 1 秒）写日志，便于事后定位

    陷阱：
    - 不要在此层做 DB / 网络调用（会污染计时本身）
    - 不要采样率 < 100%（生产观测要全量）
    """

    SLOW_REQUEST_THRESHOLD_SEC = 1.0

    async def dispatch(self, request, call_next):
        # TODO:
        # import time
        # start = time.perf_counter()
        # response = await call_next(request)
        # elapsed = time.perf_counter() - start
        # response.headers["X-Process-Time"] = f"{elapsed:.3f}"
        # if elapsed > SLOW_REQUEST_THRESHOLD_SEC:
        #     log.warning(f"slow request: {request.url.path} took {elapsed:.2f}s")
        # return response
        return await call_next(request)


# ─────────────────────────────────────────────────────────────────────────────
# 注册入口
# ─────────────────────────────────────────────────────────────────────────────

def register_middleware(app: FastAPI) -> None:
    """
    注册全部中间件。

    顺序（从外到内）：
        AuditMiddleware → AuthMiddleware → IdempotencyMiddleware →
        SecurityHeadersMiddleware → RateLimitMiddleware →
        InputSanitizerMiddleware → PerformanceMiddleware

    FastAPI 是栈结构（后注册先执行），所以代码里**反着写**：
        最里层（性能）先 add，最外层（审计）最后 add。
    """
    # 7. 性能（最内 — 最先 add）
    app.add_middleware(PerformanceMiddleware)
    # 6. 输入消毒
    app.add_middleware(InputSanitizerMiddleware)
    # 5. 限流
    app.add_middleware(RateLimitMiddleware)
    # 4. 安全响应头
    app.add_middleware(SecurityHeadersMiddleware)
    # 3. 幂等
    app.add_middleware(IdempotencyMiddleware)
    # 2. 认证
    app.add_middleware(AuthMiddleware)
    # 1. 审计（最外 — 最后 add）
    app.add_middleware(AuditMiddleware)

    # CORS 通常在最外层，由 Starlette 单独处理（不在我们的栈里数）
    # app.add_middleware(
    #     CORSMiddleware,
    #     allow_origins=settings.allowed_origins,
    #     allow_credentials=True,
    #     allow_methods=["*"],
    #     allow_headers=["*"],
    # )


# ─────────────────────────────────────────────────────────────────────────────
# 自检入口（python register_middleware.py 直接跑）
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("✅ 7 层中间件骨架可被 import")
    app = FastAPI()
    register_middleware(app)
    print("✅ register_middleware(app) 调用成功")
    print()
    print("中间件栈（从外到内）：")
    layers = [
        "AuditMiddleware           记录所有写操作（GMP ALCOA+）",
        "AuthMiddleware            JWT 验证 + 用户上下文",
        "IdempotencyMiddleware     防重复提交",
        "SecurityHeadersMiddleware CSP / X-Frame-Options / HSTS",
        "RateLimitMiddleware       Redis 滑动窗口限流",
        "InputSanitizerMiddleware  XSS / SQL 注入防护",
        "PerformanceMiddleware     响应时间计时",
    ]
    for i, line in enumerate(layers, 1):
        print(f"  [{i}] {line}")
