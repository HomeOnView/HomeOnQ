"""분석 → 페이로드 생성 → 백엔드 전송까지 묶는 실행기."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import CONFIG, Config
from .detector import analyze_sequence
from .local_queue import LocalEventQueue
from .reporter import EventReporter
from .report_generator import generate_daily_report
from .schemas import DetectedEvent, SequenceAnalysis
from .scoring import compute_daily_score
from .skeleton_source import SampleSequence, load_sequence

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo

    KST = ZoneInfo("Asia/Seoul")
except Exception:  # pragma: no cover
    KST = timezone(timedelta(hours=9))

DEFAULT_BASELINE = {"steps": 4100, "walking_minutes": 62, "night_activity_minutes": 18}

# 이벤트별 '하루 중 발생 시각' 오프셋(시연용)
TIME_OFFSETS = {
    "WALKING": timedelta(hours=6),
    "NIGHT_ACTIVITY": timedelta(hours=2),
    "TOILET_VISIT": timedelta(hours=1, minutes=30),
    "BEDROOM_STAY": timedelta(minutes=40),
    "INACTIVE": timedelta(hours=3),
    "WANDERING": timedelta(hours=1),
}


def build_summary_rows(metrics: dict, baseline: dict | None = None) -> list[dict]:
    baseline = baseline or {}
    rows = []
    steps = metrics.get("steps")
    base_steps = baseline.get("steps")
    if steps is not None:
        delta = round((steps - base_steps) / base_steps * 100) if base_steps else None
        rows.append({"key": "steps", "label": "보행", "value": steps, "unit": "걸음", "delta_percent": delta})
    if metrics.get("night_activity_minutes") is not None:
        rows.append({"key": "night_activity", "label": "야간 활동",
                     "value": metrics["night_activity_minutes"], "unit": "분", "delta_percent": None})
    if metrics.get("toilet_visits") is not None:
        rows.append({"key": "toilet", "label": "화장실 이용", "value": metrics["toilet_visits"], "unit": "회"})
    if metrics.get("bedroom_minutes") is not None:
        rows.append({"key": "bedroom", "label": "침실 체류", "value": metrics["bedroom_minutes"], "unit": "분"})
    if metrics.get("inactivity_minutes") is not None:
        rows.append({"key": "inactivity", "label": "최장 무활동", "value": metrics["inactivity_minutes"], "unit": "분"})
    if metrics.get("wandering_minutes"):
        rows.append({"key": "wandering", "label": "배회", "value": metrics["wandering_minutes"], "unit": "분"})
    return rows


@dataclass
class PipelineResult:
    sample: SampleSequence
    analysis: SequenceAnalysis
    events: list[DetectedEvent]
    behavior_payloads: list[dict[str, Any]]
    fall_payloads: list[dict[str, Any]]
    report_payload: dict[str, Any]
    report_meta: dict[str, Any]
    daily_metrics: dict[str, Any] = field(default_factory=dict)
    score: dict[str, Any] = field(default_factory=dict)
    sent: dict[str, Any] = field(default_factory=dict)

    def public_summary(self) -> dict[str, Any]:
        return {
            "scenario": self.sample.scenario,
            "label": self.sample.label,
            "description": self.sample.description,
            "duration_s": round(self.analysis.duration_s, 1),
            "events": [e.as_dict() for e in self.events],
            "segment_metrics": self.analysis.metrics,
            "metrics": self.daily_metrics,
            "score": self.score,
            "report": self.report_payload,
            "report_source": self.report_meta.get("source"),
            "behavior_count": len(self.behavior_payloads),
            "fall_count": len(self.fall_payloads),
            "detector": self.analysis.metrics.get("detector", "rule"),
            "ai_model": self.analysis.metrics.get("ai_model"),
        }


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _compact_model_summary(model: dict | None) -> dict | None:
    """리포트에 넣을 AI 모델 요약(전체 창 정보는 segment_metrics에 있다)."""
    if not model:
        return None
    keys = ("source", "model_name", "model_version", "top_class", "window", "window_count", "probabilities")
    return {k: model[k] for k in keys if k in model}


class PipelineRunner:
    def __init__(
        self,
        config: Config | None = None,
        reporter: EventReporter | None = None,
        queue: LocalEventQueue | None = None,
        classifier: object | None = None,
        load_model: bool = True,
    ):
        self.config = config or CONFIG
        self.queue = queue or LocalEventQueue(self.config.DB_PATH)
        self.reporter = reporter or EventReporter(config=self.config, local_queue=self.queue)
        # ONNX 행동 분류기는 한 번만 로드해 재사용한다. 없으면 규칙 기반으로 동작한다.
        self.classifier = classifier
        self.model_reason = "외부에서 주입된 분류기" if classifier is not None else "모델 미사용"
        if classifier is None and load_model:
            try:
                from .inference import build_classifier

                self.classifier, self.model_reason = build_classifier(self.config)
            except Exception as exc:  # numpy/onnxruntime 미설치 등 — 규칙 기반으로 계속
                self.classifier = None
                self.model_reason = f"AI 모델 모듈을 불러올 수 없습니다({exc}) → 규칙 기반 사용"
        logger.info(
            "🧠 [Pipeline] 감지기: %s (%s)",
            "규칙+ONNX" if self.classifier is not None else "규칙",
            self.model_reason,
        )

    # --- 페이로드 준비 ---
    def prepare(
        self,
        seq: SampleSequence,
        analysis: SequenceAnalysis,
        senior_name: str | None = None,
        report_date: datetime | None = None,
    ) -> PipelineResult:
        senior_name = senior_name or self.config.SENIOR_NAME
        now = datetime.now(timezone.utc)
        report_day = (report_date or now.astimezone(KST)).astimezone(KST).date()
        context = dict(seq.meta.get("daily_context") or {})
        baseline = dict(context.get("baseline") or DEFAULT_BASELINE)

        fall_events = [e for e in analysis.events if e.kind == "fall"]
        inactivity_events = [e for e in analysis.events if e.kind == "inactivity"]
        wandering_events = [e for e in analysis.events if e.kind == "wandering"]

        daily = {
            "steps": context.get("steps"),
            "night_activity_minutes": context.get("night_activity_minutes"),
            "toilet_visits": context.get("toilet_visits"),
            "bedroom_minutes": context.get("bedroom_minutes"),
            "inactivity_minutes": context.get("inactivity_minutes"),
            "wandering_minutes": context.get("wandering_minutes", 0),
            "walking_minutes": context.get("walking_minutes"),
        }
        if inactivity_events:
            daily["inactivity_minutes"] = max(
                daily.get("inactivity_minutes") or 0,
                round(max(e.duration_s for e in inactivity_events) / 60, 1),
            )
        if wandering_events:
            daily["wandering_minutes"] = max(
                daily.get("wandering_minutes") or 0,
                round(max(e.duration_s for e in wandering_events) / 60, 1),
            )
        daily = {k: v for k, v in daily.items() if v is not None}
        score = compute_daily_score(daily, baseline, fall_count=len(fall_events))

        behavior_payloads = self._behavior_payloads(daily, seq, analysis, now)
        fall_payloads = [self._fall_payload(e, seq) for e in fall_events]
        report = generate_daily_report(
            senior_name,
            report_day,
            daily,
            score["factors"],
            [e.as_dict() for e in analysis.events],
            {**score, "fall_count": len(fall_events)},
            config=self.config,
        )
        summary = {
            "metrics": daily,
            "baseline": baseline,
            "rows": build_summary_rows(daily, baseline),
            "fall_count": len(fall_events),
            "segment_metrics": analysis.metrics,
            "detector": analysis.metrics.get("detector", "rule"),
            "ai_model": _compact_model_summary(analysis.metrics.get("ai_model")),
            "projection": "daily_context" if seq.meta.get("daily_context") else "measured_only",
        }
        report_payload = {
            "report_date": report_day.isoformat(),
            "score": score["score"],
            "risk_level": score["risk_level"],
            "risk_label": score["risk_label"],
            "ui_color": score["ui_color"],
            "headline": report["headline"],
            "narrative": report["narrative"],
            "summary": summary,
            "factors": score["factors"],
            "data_status": "FINAL",
            "source": report["source"],
            "model_name": report["model_name"],
            "event_count": len(behavior_payloads) + len(fall_payloads),
            "generated_at": _iso(now),
        }
        return PipelineResult(
            sample=seq,
            analysis=analysis,
            events=analysis.events,
            behavior_payloads=behavior_payloads,
            fall_payloads=fall_payloads,
            report_payload=report_payload,
            report_meta=report,
            daily_metrics=daily,
            score={**score, "fall_count": len(fall_events)},
        )

    def _behavior_payloads(
        self, daily: dict, seq: SampleSequence, analysis: SequenceAnalysis, now: datetime
    ) -> list[dict[str, Any]]:
        common_meta = {
            "scenario": seq.scenario,
            "source": "camera-analysis" if not seq.meta.get("daily_context") else "demo-daily-context",
            "coordinate_system": "mediapipe_pose_33_normalized_image",
            "clip_seconds": analysis.metrics.get("clip_seconds"),
            "time_scale": seq.time_scale,
        }
        specs = [
            ("WALKING", daily.get("steps"), "걸음", {"walking_steps": daily.get("steps")}),
            ("NIGHT_ACTIVITY", daily.get("night_activity_minutes"), "분", {}),
            ("TOILET_VISIT", daily.get("toilet_visits"), "회", {}),
            ("BEDROOM_STAY", daily.get("bedroom_minutes"), "분", {}),
            ("INACTIVE", daily.get("inactivity_minutes"), "분", {}),
            ("WANDERING", daily.get("wandering_minutes"), "분", {}),
        ]
        payloads = []
        for activity_type, value, unit, extra in specs:
            if value is None or value == 0:
                continue
            captured = now - TIME_OFFSETS.get(activity_type, timedelta(hours=1))
            payload = {
                "event_id": str(uuid.uuid4()),
                "captured_at": _iso(captured),
                "activity_type": activity_type,
                "event_value": float(value),
                "unit": unit,
                "activity_duration_seconds": float(value) * 60 if unit == "분" else None,
                "confidence": 0.9,
                "data_quality": 0.92,
                "feature_version": "onview-pipeline-v1",
                "metadata": {**common_meta, "note": _note_for(activity_type, value, unit), **extra},
            }
            payloads.append({k: v for k, v in payload.items() if v is not None})
        return payloads

    def _fall_payload(self, event: DetectedEvent, seq: SampleSequence) -> dict[str, Any]:
        return {
            "event_id": f"sim-{uuid.uuid4()}",
            "detected_at": _iso(event.occurred_at),
            "fall_suspected": True,
            "confidence": round(float(event.confidence), 3),
            "risk_level": "HIGH" if event.confidence >= 0.75 else "MEDIUM",
            "reasoning": event.reasoning,
            "feature_summary": {**event.features, "scenario": seq.scenario, "frame_index": event.frame_index},
            "metadata": {
                "source": "camera-analysis",
                "scenario": seq.scenario,
                "coordinate_system": "mediapipe_pose_33_normalized_image",
                "label": seq.label,
            },
        }

    # --- 실행 ---
    def analyze(self, seq: SampleSequence) -> SequenceAnalysis:
        return analyze_sequence(
            seq.frames, fps=seq.fps, time_scale=seq.time_scale,
            config=self.config, label=seq.label, classifier=self.classifier,
        )

    def run_sequence(self, seq: SampleSequence, senior_name: str | None = None, send: bool = True) -> PipelineResult:
        analysis = self.analyze(seq)
        result = self.prepare(seq, analysis, senior_name)
        result.sent = {"behavior": [], "fall": [], "report": None}
        if send:
            for payload in result.behavior_payloads:
                result.sent["behavior"].append(self.reporter.report_behavior(payload))
            for payload in result.fall_payloads:
                result.sent["fall"].append(self.reporter.report_fall(payload))
            result.sent["report"] = self.reporter.report_daily_report(result.report_payload)
            self.reporter.flush_offline_queue()
        return result

    def run_file(self, path: str, senior_name: str | None = None, send: bool = True) -> PipelineResult:
        seq = load_sequence(path)
        return self.run_sequence(seq, senior_name=senior_name, send=send)

    def close(self) -> None:
        self.reporter.close()


def _note_for(activity_type: str, value: Any, unit: str) -> str:
    if activity_type == "WALKING":
        return f"분석 구간에서 {value:,.0f}걸음을 추정했습니다"
    if activity_type == "NIGHT_ACTIVITY":
        return f"야간 시간대 활동 {value:.0f}분"
    if activity_type == "TOILET_VISIT":
        return f"화장실 이용 {value:.0f}회"
    if activity_type == "BEDROOM_STAY":
        return f"침실 체류 {value:.0f}분"
    if activity_type == "INACTIVE":
        return f"장시간 무활동 {value:.0f}분"
    if activity_type == "WANDERING":
        return f"좌우 반복 이동(배회) {value:.0f}분"
    return f"{activity_type} {value}{unit}"
