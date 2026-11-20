"""MediaPipe Tasks 포즈 모델(약 5.8MB)을 내려받는다.

    python scripts/download_models.py
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
)


def main() -> int:
    target = ROOT / "models" / "pose_landmarker_lite.task"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 1_000_000:
        print(f"이미 있음: {target} ({target.stat().st_size:,} bytes)")
        return 0
    print(f"내려받는 중: {MODEL_URL}")
    urllib.request.urlretrieve(MODEL_URL, target)
    print(f"완료: {target} ({target.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
