from pydantic import BaseModel, Field


class Token(BaseModel):
    """Access-token-only response, kept for the OAuth2 password flow contract."""

    access_token: str
    token_type: str = "bearer"


class TokenPair(Token):
    refresh_token: str


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)
