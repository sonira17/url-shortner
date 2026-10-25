from pydantic import BaseModel, HttpUrl, ConfigDict
from datetime import datetime
from pydantic import Field

class URLCreate(BaseModel):
    long_url: HttpUrl
    days : int =Field(default=7, ge=1, le=365)


class URLResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    short_code: str
    long_url: HttpUrl
    created_at: datetime |None =None
    expired_at: datetime | None = None

class URLUpdate(BaseModel):
    long_url : HttpUrl