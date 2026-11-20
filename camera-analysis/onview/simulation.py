"""웹앱 시연용: 샘플 시나리오를 분석해 전송용 페이로드까지 만든다(전송은 호출 측)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import CONFIG, Config
from .local_queue import LocalEventQueue
from .pipeline import PipelineResult, PipelineRunner
from .reporter import EventReporter
from .skeleton_source import SCENARIO_FILES, load_sequence


@dataclass
class ScenarioResult:
    result: PipelineResult

    @property
    def behavior_payloads(self) -> list[dict[str, Any]]:
        return self.result.behavior_payloads

    @property
    def fall_payloads(self) -> list[dict[str, Any]]:
        return self.result.fall_payloads

    @property
    def report_payload(self) -> dict[str, Any]:
        return self.result.report_payload

    def public_summary(self) -> dict[str, Any]:
        return self.result.public_summary()


def analyze_scenario(
    scenario: str,
    sample_path: str | Path | None = None,
    senior_name: str = "강O순 어르신",
    config: Config | None = None,
) -> ScenarioResult:
    cfg = config or CONFIG
    path = Path(sample_path) if sample_path else cfg.SAMPLE_DIR / SCENARIO_FILES[scenario]
    seq = load_sequence(path)
    runner = PipelineRunner(
        config=cfg,
        reporter=EventReporter(mode="MOCK", config=cfg, local_queue=LocalEventQueue(":memory:")),
        queue=LocalEventQueue(":memory:"),
    )
    analysis = runner.analyze(seq)
    prepared = runner.prepare(seq, analysis, senior_name=senior_name)
    return ScenarioResult(result=prepared)
