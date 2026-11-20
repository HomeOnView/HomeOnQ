"""시간대 직렬화 도우미.

SQLite는 DateTime(timezone=True)에 저장한 시각을 naive로 돌려주므로, 응답에서
오프셋이 빠지면 앱이 로컬 시간으로 잘못 해석한다. 저장 규칙은 'UTC'이므로
naive 값은 UTC로 간주해 항상 오프셋을 붙여 내보낸다.
"""
from __future__ import annotations

from datetime import datetime, timezone


def iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
