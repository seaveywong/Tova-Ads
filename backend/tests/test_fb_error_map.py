"""FB_ERROR_MAP / classify_fb_error 纯函数测试（app.core.fb_client）。

错误翻译是所有 FB 写操作失败时的兜底文案出口：映射缺失或术语泄漏会直接打到
用户界面（部署清单/管理器提示），是 UI 文案质量的一部分。
"""
import re

from app.core.fb_client import FB_ERROR_MAP, classify_fb_error

# 未加工的报错杂音——出现在人话文案里 = 技术细节泄漏给用户
_RAW_JARGON = (
    "Exception", "Traceback", "traceback",
    "error_subcode", "error_user_msg", "error_user_title",
    "GraphMethodException", "OAuthException", "HTTP 5",
)
_CJK = re.compile(r"[一-鿿]")


class TestFbErrorMap:
    def test_every_entry_is_nonempty_category_friendly_pair(self):
        """每个 code 映射到 (非空 category, 非空 friendly) 二元组。"""
        for code, val in FB_ERROR_MAP.items():
            assert isinstance(code, int) and code > 0, f"非法 code 键: {code!r}"
            assert isinstance(val, tuple) and len(val) == 2, f"code {code} 不是二元组: {val!r}"
            category, friendly = val
            assert isinstance(category, str) and category, f"code {code} category 为空"
            assert isinstance(friendly, str) and friendly, f"code {code} friendly 为空"

    def test_key_codes_have_expected_category(self):
        """关键码语义正确：190 令牌失效 / 200 权限 / 100 参数 / 4,17,32 限流。"""
        assert FB_ERROR_MAP[190][0] == "token_expired"
        assert FB_ERROR_MAP[200][0] == "permissions"
        assert FB_ERROR_MAP[100][0] == "invalid_param"
        for code in (4, 17, 32):
            assert FB_ERROR_MAP[code][0] == "rate_limited", f"code {code} 应为 rate_limited"

    def test_friendly_is_chinese_human_text_without_raw_jargon(self):
        """friendly 必须是中文人话：至少含一个 CJK 字符，且不泄漏原始报错杂音。

        允许保留：FB/Meta/Token 等专有名词、括号里指引性的 API 字段名
        （如 verified_identity_id——那是给用户的操作指引，不是泄漏）。
        """
        for code, (_, friendly) in FB_ERROR_MAP.items():
            assert _CJK.search(friendly), f"code {code} friendly 无中文: {friendly!r}"
            for jargon in _RAW_JARGON:
                assert jargon not in friendly, f"code {code} 泄漏技术术语 {jargon!r}: {friendly!r}"


class TestClassifyFbError:
    def test_known_code_returns_map_entry(self):
        """已知 code 直接命中映射。"""
        category, friendly = classify_fb_error({"code": 190, "message": "whatever"})
        assert category == "token_expired"
        assert friendly == FB_ERROR_MAP[190][1]

    def test_subcode_takes_priority_over_code(self):
        """error_subcode 优先于 code（批AZ 2446079 挂在 subcode 位，code 位是 17）。"""
        category, _ = classify_fb_error(
            {"code": 17, "error_subcode": 2446079, "message": "User request limit reached"})
        assert category == "rate_limited"

    def test_code_100_missing_permission_maps_to_permissions(self):
        """code 100 + Missing Permission = 令牌缺权限而非参数错，须给重新授权指引。"""
        category, friendly = classify_fb_error(
            {"code": 100, "message": "(#100) Missing Permission: business_management"})
        assert category == "permissions"
        assert "重新授权" in friendly

    def test_non_discrimination_message_falls_back_to_cert_required(self):
        """未知 code 但消息含 non-discrimination → 非歧视政策认证指引。"""
        category, _ = classify_fb_error(
            {"code": 999999, "message": "Please complete the non-discrimination policy verification"})
        assert category == "cert_required"

    def test_unknown_error_keeps_user_msg_for_diagnosis(self):
        """未知错误保留 error_user_msg 原文（生产实测：安全锁定的提示只在 user_msg 里）。"""
        category, friendly = classify_fb_error(
            {"code": 999999, "message": "raw english detail",
             "error_user_msg": "验证你的账户之前广告不会投放"})
        assert category == "generic"
        assert "验证你的账户之前广告不会投放" in friendly
