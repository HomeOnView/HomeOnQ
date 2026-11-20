from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

GENDERS = {"여성", "남성", "기타", "미입력"}


class SeniorProfileUpdate(BaseModel):
    """보호자 앱에서 수정 가능한 어르신 프로필. 보낸 필드만 갱신한다."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    birth_date: date | None = None
    gender: str | None = Field(default=None, max_length=10)
    height_cm: float | None = Field(default=None, ge=50, le=250)
    weight_kg: float | None = Field(default=None, ge=20, le=250)
    medical_conditions: list[str] | None = Field(default=None, max_length=20)
    photo_url: str | None = Field(default=None, max_length=1024)
    emergency_contact: str | None = Field(default=None, max_length=40)
    memo: str | None = Field(default=None, max_length=2000)

    @field_validator("gender")
    @classmethod
    def valid_gender(cls, v: str | None) -> str | None:
        if v is not None and v not in GENDERS:
            raise ValueError("gender must be one of 여성, 남성, 기타, 미입력")
        return v

    @field_validator("medical_conditions")
    @classmethod
    def clean_conditions(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        cleaned = []
        for item in v:
            text = str(item).strip()
            if text and text not in cleaned:
                if len(text) > 40:
                    raise ValueError("each condition must be 40 characters or fewer")
                cleaned.append(text)
        return cleaned

    @field_validator("photo_url")
    @classmethod
    def valid_photo(cls, v: str | None) -> str | None:
        if v and not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("photo_url must be an http(s) URL")
        return v


class DailyReportIn(BaseModel):
    """엣지 파이프라인이 전송하는 안심 리포트."""

    model_config = ConfigDict(extra="forbid")

    report_date: date
    score: int | None = Field(default=None, ge=0, le=100)
    risk_level: str = Field(default="UNKNOWN", max_length=20)
    risk_label: str = Field(default="확인 필요", max_length=20)
    ui_color: str = Field(default="#64748b", max_length=20)
    headline: str | None = Field(default=None, max_length=200)
    narrative: str | None = Field(default=None, max_length=8000)
    summary: dict[str, Any] = Field(default_factory=dict)
    factors: dict[str, Any] = Field(default_factory=dict)
    data_status: str = Field(default="RECEIVED", max_length=30)
    source: str = Field(default="pipeline-rule", max_length=40)
    model_name: str | None = Field(default=None, max_length=80)
    event_count: int = Field(default=0, ge=0)
    generated_at: datetime | None = None


class DemoSimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: Literal["normal", "fall", "inactive", "wandering"] = "fall"
    senior_id: str | None = None
