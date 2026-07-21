"""FB 接口 Schema。"""
from pydantic import BaseModel


class StoreCredentialIn(BaseModel):
    access_token: str
    type: str = "user_token"
    alias: str = ""
    token_type: str = "user"  # manage / operate / user
    token_source: str = "manual"  # oauth(App授权) / manual(手粘)


class FbCredentialOut(BaseModel):
    id: int
    type: str
    status: str
    alias: str | None = None
    fb_user_name: str | None = None


class ImportAccountsIn(BaseModel):
    account_ids: list[str]
