"""wallet_apply 记账测试（stub session，不连库）——幂等键 / 余额下限 / 正常记账。

钱包是资金安全核心（批1 铁律：余额变更唯一入口 wallet_apply），三条硬不变量：
- 幂等键命中 → 返回既有流水，绝不二次扣/入（0109 重构：只认 idempotency 键）；
- 扣款后余额为负（容差 0.005）→ InsufficientBalance + 回滚；
- 正常记账 → balance_after 断言 + 乐观锁 version 自增。
"""
import pytest

from app.core.wallet import InsufficientBalance, wallet_apply
from app.models.wallet import WalletAccount, WalletTxn


class _StubQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def with_for_update(self):
        return self

    def first(self):
        return self._result


class _StubSession:
    """最小 Session stub：按模型返回预设查询结果，记录 add/commit/rollback 与查询轨迹。"""

    def __init__(self, txn_hit=None, account=None):
        self._txn_hit = txn_hit
        self._account = account
        self.queried_models = []
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    def query(self, model):
        self.queried_models.append(model)
        if model is WalletTxn:
            return _StubQuery(self._txn_hit)
        if model is WalletAccount:
            return _StubQuery(self._account)
        raise AssertionError(f"意外查询模型: {model}")

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _account(balance=100.00, version=3):
    """构造内存账户。balance 必须是 float——真 ORM Float 列从 PG 回来就是浮点
    （wallet_apply 异常消息会对它做 :.2f 格式化，字符串是 stub 造假）。"""
    acc = WalletAccount(tenant_id=1)
    acc.balance_usd = float(balance)
    acc.version = version
    return acc


class TestWalletApplyIdempotency:
    def test_existing_idempotency_key_returns_existing_txn_without_side_effects(self):
        """幂等键已存在 → 返回已有流水；不查账户、不 add、不 commit（不重复记账）。"""
        hit = WalletTxn(tenant_id=1, type="charge", amount_usd=-5, balance_after=95,
                        ref_type="domain_order", ref_id=7, idempotency="order-7")
        db = _StubSession(txn_hit=hit, account=_account())
        out = wallet_apply(db, 1, "charge", -5, "domain_order", ref_id=7,
                           idempotency="order-7")
        assert out is hit
        assert db.queried_models == [WalletTxn], "幂等命中后不应再查账户"
        assert db.added == []
        assert db.commits == 0
        assert db.rollbacks == 0


class TestWalletApplyBalanceGuard:
    def test_insufficient_balance_raises_and_rolls_back(self):
        """余额不足 → InsufficientBalance + 回滚，余额与流水都不动。"""
        acc = _account(balance="10.00")
        db = _StubSession(account=acc)
        with pytest.raises(InsufficientBalance):
            wallet_apply(db, 1, "charge", -25, "domain_order", ref_id=1,
                         idempotency="order-1")
        assert db.rollbacks == 1
        assert db.commits == 0
        assert db.added == []
        assert float(acc.balance_usd) == 10.00

    def test_exact_balance_charge_allowed(self):
        """扣到恰好 0 允许（止损场景：清空余额不算不足）。"""
        db = _StubSession(account=_account(balance="10.00"))
        txn = wallet_apply(db, 1, "charge", -10, "test", idempotency="t-zero")
        assert txn.balance_after == 0.0
        assert db.commits == 1


class TestWalletApplyNormal:
    def test_charge_updates_balance_version_and_txn_snapshot(self):
        """正常扣款：balance_after=前+amount、账户余额更新、乐观锁 version+1、恰好一次 commit。"""
        acc = _account(balance="100.00", version=3)
        db = _StubSession(account=acc)
        txn = wallet_apply(db, 1, "charge", -30, "domain_order", ref_id=9,
                           txid="TX1", note="续费", user_id=2, idempotency="order-9")
        assert isinstance(txn, WalletTxn)
        assert txn.tenant_id == 1
        assert txn.type == "charge"
        assert txn.amount_usd == -30
        assert txn.balance_after == 70.0
        assert txn.ref_type == "domain_order" and txn.ref_id == 9
        assert txn.idempotency == "order-9" and txn.txid == "TX1"
        assert txn.created_by == 2
        assert float(acc.balance_usd) == 70.0
        assert acc.version == 4
        assert db.added == [txn]
        assert db.commits == 1 and db.rollbacks == 0

    def test_deposit_amounts_round_to_two_decimals(self):
        """入账金额与余额都 round 到 2 位（浮点 0.1+0.2 不得写进流水）。"""
        db = _StubSession(account=_account(balance="10.00"))
        txn = wallet_apply(db, 1, "deposit", 0.1 + 0.2, "topup", txid="T9")
        assert txn.amount_usd == 0.3
        assert txn.balance_after == 10.3

    def test_empty_idempotency_skips_dedup_query(self):
        """idempotency 为空 = 不去重（人工 adjust），跳过幂等查库直接记账。"""
        db = _StubSession(account=_account(balance="10.00"))
        wallet_apply(db, 1, "adjust", 5, "manual", note="手工调整")
        assert WalletTxn not in db.queried_models
        assert db.commits == 1
