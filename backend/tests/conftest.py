"""pytest 环境引导——阶段1：纯单元测试（不连 DB、不联网），只测业务逻辑函数。

被测模块的 import 链在模块加载时会做两件事，必须在任何 app.* import 之前垫好：

1. ``app.core.config``（pydantic-settings）的 DATABASE_URL / DATABASE_SUPER_URL /
   JWT_SECRET 是必填项——本地无 .env 时直接 ValidationError。这里 setdefault
   测试假值（绝不覆盖真实环境变量，.env/.env 变量优先级更高）。
2. ``app.core.database`` 在 import 时就 ``create_engine(...)``：engine 本身惰性
   不连库，但会立即 import PG 驱动（psycopg2），本地没装驱动时 ModuleNotFoundError。
   单测阶段不触库，统一用离线 stub 替换 create_engine。

将来做真库集成测试（CI 起 postgres service）时，把 stub 换成按 marker 生效即可。
"""
import os
import sys

# 让 `import app.*` 可解析（backend/ 进 sys.path，pytest.ini 同目录）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 1) 必填 env 假值（只补缺，不覆盖）
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://unit:test@127.0.0.1:5432/unit_test")
os.environ.setdefault("DATABASE_SUPER_URL", os.environ["DATABASE_URL"])
os.environ.setdefault("JWT_SECRET", "unit-test-only-secret-0123456789abcdef")

# 2) 离线 engine stub（须在任何 app.* import 之前；conftest 先于测试模块加载）
import sqlalchemy


class _OfflineEngine:
    """占位 engine：单测不应执行 SQL，真连接直接报错暴露误用。"""

    def connect(self):
        raise RuntimeError("单元测试不应触碰数据库连接（做集成测试请配真 PG）")


sqlalchemy.create_engine = lambda url, *a, **kw: _OfflineEngine()  # noqa: E731
