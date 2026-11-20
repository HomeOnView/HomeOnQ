"""시연용 샘플 관절좌표 시퀀스를 samples/에 생성한다.

    python scripts/generate_samples.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from onview.skeleton_source import SCENARIO_FILES, save_sequence  # noqa: E402
from onview.synthetic import BUILDERS  # noqa: E402


def main() -> int:
    out_dir = ROOT / "samples"
    for scenario, builder in BUILDERS.items():
        data = builder()
        path = save_sequence(out_dir / SCENARIO_FILES[scenario], data)
        print(f"{scenario:10s} → {path.name}  frames={len(data['frames'])} fps={data['fps']} scale={data['time_scale']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
