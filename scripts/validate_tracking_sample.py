from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from lidar_label_tool.app.config import default_config_path, load_config
from lidar_label_tool.io.adapters.factory import open_dataset_adapter
from lidar_label_tool.services.tracking_qa import TrackingQaOptions, validate_tracking_sample


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="원본 라벨/포인트를 변경하지 않고 인접 프레임 추적 표본을 비교합니다. JSON은 stdout에만 출력합니다.",
    )
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--lidar-id", required=True, help="비교할 단일 LiDAR ID (예: TOP)")
    parser.add_argument("--profile-id")
    parser.add_argument("--max-frames", type=int, default=4)
    parser.add_argument("--max-objects-per-pair", type=int, default=12)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--max-distance-m", type=float, default=4.0)
    parser.add_argument("--config", type=Path, default=default_config_path())
    args = parser.parse_args(argv)
    try:
        adapter = open_dataset_adapter(args.dataset, profile_id=args.profile_id)
        config = load_config(args.config)
        report = validate_tracking_sample(
            adapter, config["source_class_mappings"], lidar_id=args.lidar_id,
            options=TrackingQaOptions(
                args.max_frames, args.max_objects_per_pair, args.start_index, args.max_distance_m,
            ),
        )
    except (OSError, ValueError, KeyError, AssertionError) as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if report["summary"]["sample_count"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
