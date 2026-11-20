from pydantic import BaseModel, Field, ConfigDict, field_validator

class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    @field_validator('email')
    @classmethod
    def valid_email(cls, v):
        if v.count('@') != 1 or '.' not in v.rsplit('@', 1)[-1]: raise ValueError('Invalid email')
        return v
    password: str = Field(min_length=12, max_length=128)

class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    @field_validator('email')
    @classmethod
    def valid_email(cls, v):
        if v.count('@') != 1 or '.' not in v.rsplit('@', 1)[-1]: raise ValueError('Invalid email')
        return v
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = 'bearer'
    expires_in: int

class GuardianResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    is_active: bool

class DeviceCreate(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)
    senior_id: str

class DeviceResponse(BaseModel):
    id: str
    device_id: str
    senior_id: str
    status: str
    last_seen_at: str | None = None

class DeviceIssuedResponse(DeviceResponse):
    device_token: str
