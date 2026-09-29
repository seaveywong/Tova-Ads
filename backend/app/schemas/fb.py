"""FB 接口 Schema。"""
from pydantic import BaseModel


class StoreCredentialIn(BaseModel):
    access_token: str
    type: str = "user_token"
    alias: str = ""
    token_type: str = "user"  # manage / operate / user
    token_source: str = "manual"  # oauth(App授权) / manual(手粘)

    def model_post_init(self, __ctx) -> None:
        # schema 默认值与请求缺省不可区分——重导令牌时不传 token_type 会被静默降回 "user"。
        # 显式 None 标记"未传"，路由侧凭 is_set 决定保留旧值还是覆盖。
        if not self.__pydantic_fields_set__ or "token_type" not in self.__pydantic_fields_set__:
            object.__setattr__(self, "_token_type_set", False)
        else:
            object.__setattr__(self, "_token_type_set", True)


class FbCredentialOut(BaseModel):
    id: int
    type: str
    status: str
    alias: str | None = None
    fb_user_name: str | None = None


class ImportAccountsIn(BaseModel):
    account_ids: list[str]
