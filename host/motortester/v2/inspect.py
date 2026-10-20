"""Read, summarize and export recorded raw samples without Qt or a device."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from .core import load, analyze, export_csv


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Чтение записи Мотортестера V2 без GUI; результат — JSON."
    )
    parser.add_argument("path", type=Path, help="Исходный файл .mtv2 или .mtcap")
    parser.add_argument("--csv", type=Path, help="Экспорт выбранного участка в CSV и CSV.json")
    parser.add_argument("--start-index", type=int, help="Первый абсолютный индекс участка")
    parser.add_argument("--stop-index", type=int, help="Последняя граница участка, не включается")
    args = parser.parse_args(argv)
    try:
        recording = load(args.path)
        requested_start = args.start_index if args.start_index is not None else recording.start_index
        requested_stop = args.stop_index if args.stop_index is not None else recording.end_index
        if args.start_index is not None or args.stop_index is not None:
            recording = recording.slice(requested_start, requested_stop)
        result = {
            "file": str(args.path.resolve()),
            "session_id": recording.session_id,
            "source": recording.source,
            "channel_id": recording.input_profile.channel_id,
            "channel_name": recording.channel_name,
            "ui_profile": recording.ui_profile,
            "voltage_state": recording.input_profile.state,
            "input_profile": asdict(recording.input_profile),
            "sample_rate_hz": recording.sample_rate_hz,
            "time_basis": recording.time_basis,
            "sample_count": recording.sample_count,
            "requested_range": [requested_start, requested_stop],
            "available_range": [recording.start_index, recording.end_index],
            "duration_s": recording.duration_s,
            "gaps": [asdict(gap) for gap in recording.gaps],
            "measurements": asdict(analyze(recording)),
        }
        if args.csv:
            csv_path, json_path = export_csv(args.csv, recording)
            result["export"] = {"csv": str(csv_path.resolve()), "metadata": str(json_path.resolve())}
    except (OSError, ValueError) as exc:
        print(f"Не удалось прочитать или экспортировать запись: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
