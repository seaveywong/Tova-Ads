-- ============================================================
-- Tove Ads 2.0 数据库初始化（以 postgres 超管执行）
-- 用法：sudo -u postgres psql -f db/init.sql
-- 跑完后再 cd backend && alembic upgrade head（建表+RLS+种子数据）
-- ============================================================

-- 角色（密码改成你的）
CREATE ROLE toveads_app LOGIN PASSWORD 'CHANGE_ME';
CREATE ROLE toveads_super LOGIN BYPASSRLS PASSWORD 'CHANGE_ME';

-- 数据库
CREATE DATABASE toveads OWNER postgres;
\c toveads

-- schema 权限
GRANT USAGE ON SCHEMA public TO toveads_app, toveads_super;

-- ============================================================
-- alembic upgrade head 后跑这段（catch-all GRANT，防个别迁移漏 GRANT）
-- ============================================================
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app, toveads_super;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_app, toveads_super;
-- ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO toveads_app, toveads_super;
-- ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO toveads_app, toveads_super;
