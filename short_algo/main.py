import json
import sys

from .scanner import run_scan, save_report


def main():
    report = run_scan()
    paths = save_report(report)

    summary = {
        "universe": report["universe_count"],
        "fast_success": report["fast_success"],
        "deep_success": report["deep_success"],
        "status_counts": report["status_counts"],
        "top": [
            {
                "symbol": row["symbol"],
                "status": row["status"],
                "score": row["score"],
                "entry": row["entry"],
                "stop": row["stop"],
                "tp1": row["tp1"],
            }
            for row in report["results"][:10]
        ],
        "files": paths,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))

    # Data-source failures should make Actions visibly fail instead of silently
    # producing an empty "successful" scan.
    if report["fast_success"] == 0 or report["deep_success"] == 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
