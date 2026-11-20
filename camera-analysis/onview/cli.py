"""홈온큐 자세분석 파이프라인 CLI.

  python -m onview.cli list
  python -m onview.cli analyze --scenario fall --json
  python -m onview.cli demo --scenario fall --server http://localhost:8000 \\
      --device-token demo-edge-token-homeonq-0001
  python -m onview.cli mediapipe-check --image samples/standing.jpg
  python -m onview.cli serve --source 0 --server http://localhost:8000
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from .config import CONFIG, load_config
from .local_queue import LocalEventQueue
from .pipeline import PipelineRunner
from .pose_analyzer import PoseAnalyzer
from .reporter import EventReporter
from .schemas import FrameData, HealthMetrics
from .skeleton_source import SCENARIO_FILES, analyze_sample, list_samples, load_sequence


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_list(_: argparse.Namespace) -> int:
    print(f"샘플 디렉터리: {CONFIG.SAMPLE_DIR}")
    for path in list_samples(CONFIG.SAMPLE_DIR):
        seq = load_sequence(path)
        print(f"- {path.name:20s} {seq.label:8s} frames={len(seq.frames):4d} fps={seq.fps:g} time_scale={seq.time_scale:g}")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    name = args.sample or SCENARIO_FILES[args.scenario]
    path = CONFIG.SAMPLE_DIR / name
    seq = load_sequence(path)
    analysis = analyze_sample(path)
    payload = {
        "sample": path.name,
        "label": seq.label,
        "duration_s": round(analysis.duration_s, 1),
        "events": [e.as_dict() for e in analysis.events],
        "metrics": analysis.metrics,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"[{seq.label}] {seq.description}")
    print(f"  길이 {analysis.duration_s:.1f}s / 프레임 {len(seq.frames)} / fps {seq.fps:g}")
    print(f"  지표: {analysis.metrics}")
    if analysis.events:
        for e in analysis.events:
            print(f"  ⚠️ {e.event_type} (신뢰도 {e.confidence:.2f}) {e.reasoning}")
    else:
        print("  ✅ 특이 이벤트 없음")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    cfg = load_config(
        SERVER_MODE=args.mode,
        SERVER_URL=args.server,
        DEVICE_TOKEN=args.device_token,
        DB_PATH=args.db,
        SENIOR_NAME=args.senior,
    )
    queue = LocalEventQueue(cfg.DB_PATH)
    reporter = EventReporter(config=cfg, local_queue=queue)
    runner = PipelineRunner(config=cfg, reporter=reporter, queue=queue)
    try:
        scenarios = [args.scenario] if args.scenario != "all" else list(SCENARIO_FILES)
        for scenario in scenarios:
            path = cfg.SAMPLE_DIR / SCENARIO_FILES[scenario]
            result = runner.run_file(str(path), senior_name=cfg.SENIOR_NAME, send=args.mode == "HTTP" or args.send)
            print(f"=== {scenario}: 탐지 {len(result.events)}건 / 행동 {len(result.behavior_payloads)}건 / 낙상 {len(result.fall_payloads)}건")
            print(f"    점수 {result.score['score']} ({result.score['risk_label']}), 리포트 출처 {result.report_meta['source']}")
            if result.report_meta.get("fallback_reason"):
                print(f"    ↳ {result.report_meta['fallback_reason']}")
            print(f"    전송 결과 {result.sent}")
            print(f"    오프라인 큐 잔여 {queue.count()}건")
        return 0
    finally:
        runner.close()


def cmd_mediapipe_check(args: argparse.Namespace) -> int:
    analyzer = PoseAnalyzer(use_mock=False)
    print(f"백엔드: {analyzer.backend}")
    if analyzer.fallback_reason:
        print(f"↳ MediaPipe 사용 불가: {analyzer.fallback_reason}")
    try:
        landmarks = analyzer.estimate_image(args.image)
    except Exception as exc:
        print(f"❌ 추출 실패: {exc}")
        return 1
    if not landmarks:
        print("❌ 사람 자세를 찾지 못했습니다.")
        return 1
    print(f"✅ {len(landmarks)}개 관절 좌표 추출")
    names = {0: "nose", 11: "left_shoulder", 12: "right_shoulder", 23: "left_hip", 24: "right_hip",
             27: "left_ankle", 28: "right_ankle"}
    for idx, name in names.items():
        x, y, z, v = landmarks[idx]
        print(f"   {name:15s} x={x:.3f} y={y:.3f} z={z:+.3f} vis={v:.2f}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:  # pragma: no cover - 상시 실행
    from .health_monitor import HealthMonitor
    from .video_input import CameraStream

    cfg = load_config(SERVER_MODE="HTTP", SERVER_URL=args.server, DEVICE_TOKEN=args.device_token)
    metrics = HealthMetrics()
    queue = LocalEventQueue(cfg.DB_PATH)
    reporter = EventReporter(config=cfg, local_queue=queue)
    monitor = HealthMonitor(metrics, reporter, queue, config=cfg)
    analyzer = PoseAnalyzer(metrics, config=cfg, use_mock=False)
    source = int(args.source) if str(args.source).isdigit() else args.source
    stream = CameraStream(source, metrics)
    print(f"카메라: {source} / 포즈 백엔드: {analyzer.backend} / 서버: {cfg.SERVER_URL}")
    stream.start()
    monitor.start()
    frames, last_frame_time = 0, 0.0
    try:
        while True:
            data = stream.get_latest_frame(timeout=2.0)
            if data is None:
                time.sleep(0.5)
                continue
            analyzer.process_frame(data)
            frames += 1
            last_frame_time = time.monotonic()
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("\n중지합니다.")
    finally:
        stream.stop()
        monitor.stop()
        analyzer.close()
        reporter.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="onview", description="홈온큐 자세·동작 분석 파이프라인")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="샘플 시퀀스 목록")

    p = sub.add_parser("analyze", help="샘플 시퀀스 분석")
    p.add_argument("--scenario", default="normal", choices=list(SCENARIO_FILES))
    p.add_argument("--sample", help="samples/ 안의 파일명 직접 지정")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("demo", help="분석 후 백엔드로 전송")
    p.add_argument("--scenario", default="all", choices=[*SCENARIO_FILES, "all"])
    p.add_argument("--server", default=CONFIG.SERVER_URL)
    p.add_argument("--device-token", default=CONFIG.DEVICE_TOKEN)
    p.add_argument("--senior", default=CONFIG.SENIOR_NAME)
    p.add_argument("--mode", default="HTTP", choices=["HTTP", "MOCK"])
    p.add_argument("--send", action="store_true", help="MOCK 모드에서도 전송 시도")
    p.add_argument("--db", default=CONFIG.DB_PATH)

    p = sub.add_parser("mediapipe-check", help="이미지에서 MediaPipe 관절 추출 확인")
    p.add_argument("--image", required=True)

    p = sub.add_parser("serve", help="카메라 스트림 상시 분석(개발용)")
    p.add_argument("--source", default=str(CONFIG.CAMERA_SOURCE))
    p.add_argument("--server", default=CONFIG.SERVER_URL)
    p.add_argument("--device-token", default=CONFIG.DEVICE_TOKEN)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    return {
        "list": cmd_list,
        "analyze": cmd_analyze,
        "demo": cmd_demo,
        "mediapipe-check": cmd_mediapipe_check,
        "serve": cmd_serve,
    }[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
