"""数据库引擎 + 会话 + RLS 上下文管理。

关键：所有业务查询必须在 tenant_ctx 内执行，把 tenant_id/is_superadmin
设进 PG 会话变量，RLS 策略据此过滤（见 09 多租户隔离）。
"""
from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from .config import settings

# pool_pre_ping: 连接断自动重连；future: SQLAlchemy 2.0 风格
engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=20, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True, expire_on_commit=False)

# system 连接（toveads_super，BYPASSRLS）——用于注册/登录/平台超管等无租户上下文的操作
super_engine = create_engine(settings.database_super_url, pool_pre_ping=True, pool_size=5, future=True)
SuperSessionLocal = sessionmaker(bind=super_engine, autoflush=False, autocommit=False, future=True, expire_on_commit=False)

Base = declarative_base()


def get_db():
    """FastAPI 依赖：每个请求一个 DB session（toveads_app，受 RLS）。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_system_db():
    """FastAPI 依赖：system session（toveads_super，BYPASSRLS）。注册/登录用。"""
    db = SuperSessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def tenant_ctx(db: Session, tenant_id: int, is_superadmin: bool = False):
    """设置 RLS 会话上下文（请求/操作期间）。

    必须在事务内调用。SET LOCAL 随事务结束自动清，防泄漏到下一请求。
    平台超管用 BYPASSRLS 角色（toveads_super）连接，或这里 is_superadmin=True。
    """
    db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
    db.execute(
        text("SET LOCAL app.is_superadmin = :s"),
        {"s": "true" if is_superadmin else "false"},
    )
    yield


def acquire_run_lock(key: int):
    """Postgres session-level advisory lock（多 worker 单调度用）。

    gunicorn 多 worker 各起 APScheduler → 同一 job 被多 worker 重复执行（TG spam 根因）。
    每个 job 运行前调此：拿到锁的 worker 才执行，其余跳过。返回持锁连接（必须配 release_run_lock 释放）。
    ⚠️ 不能只 .close()——连接回池但底层 PG backend 不死，锁会卡住。必须显式 pg_advisory_unlock。
    """
    conn = super_engine.connect()
    got = conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar()
    if got:
        return conn
    conn.close()
    return None


def release_run_lock(conn, key: int):
    """显式释放 advisory lock + 关连接（必须在 finally 调）。"""
    try:
        conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
    except Exception:
        pass
    conn.close()
