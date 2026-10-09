import os
from datetime import datetime, timedelta, timezone

import requests

VN_TZ = timezone(timedelta(hours=7))


def _fmt(value):
    if value is None:
        return "-"
    value = float(value)
    if abs(value) >= 100:
        return f"{value:,.3f}"
    if abs(value) >= 1:
        return f"{value:.5f}".rstrip("0").rstrip(".")
    return f"{value:.8f}".rstrip("0").rstrip(".")


def _scan_time_vn(value):
    if not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return str(value)


def _credentials():
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("SHORT_TELEGRAM_BOT_TOKEN")
    personal = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("SHORT_TELEGRAM_CHAT_ID")
    group = os.getenv("TELEGRAM_GROUP_CHAT_ID")
    if not token:
        print("Telegram skipped: missing bot token.")
        return None, []

    chat_ids = []
    for value in (personal, group):
        if value and value not in chat_ids:
            chat_ids.append(value)
    if not chat_ids:
        print("Telegram skipped: missing chat IDs.")
        return None, []
    return token, chat_ids


def _split_text(text, max_chars=3800):
    if len(text) <= max_chars:
        return [text]
    chunks, current = [], []
    for block in text.split("\n\n"):
        candidate = "\n\n".join(current + [block])
        if len(candidate) <= max_chars:
            current.append(block)
            continue
        if current:
            chunks.append("\n\n".join(current))
            current = []
        if len(block) <= max_chars:
            current = [block]
        else:
            for start in range(0, len(block), max_chars):
                chunks.append(block[start:start + max_chars])
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _tier_label(tier):
    return {
        "A+": "🟣 A+ · E1+E2",
        "A": "🟢 A · E2 QUALITY",
        "B": "🔵 B · E1 EMA",
        "C": "🟡 C · D BASE",
    }.get(tier, str(tier or "-"))


def build_text(report, max_rows=8):
    rows = (report.get("new_m2_signals") or [])[:max_rows]
    counts = report.get("m2_live_counts") or {}
    outcome = report.get("outcome_summary") or {}

    lines = [
        "🔻 M2 SHORT LIVE · V4.4.18",
        "=" * 30,
        f"Scan VN: {_scan_time_vn(report.get('finished_at'))}",
        (
            f"MEXC {report.get('universe_count', 0)} | "
            f"Deep {report.get('deep_success', 0)}/{report.get('deep_requested', 0)}"
        ),
        (
            f"Fresh: {len(rows)} | "
            f"A+ {counts.get('A+', 0)} · A {counts.get('A', 0)} · "
            f"B {counts.get('B', 0)} · C {counts.get('C', 0)}"
        ),
        (
            f"Outcome ledger: open {outcome.get('open_signals', 0)} | "
            f"closed {outcome.get('closed_signals', 0)}"
        ),
        "Core: Risk-Off + S4 Macro Bear → breakdown → no reclaim/lower highs → watch 24–48h → 1H confirm",
    ]

    if not rows:
        lines += [
            "",
            "Không có tín hiệu M2-D mới trong run này.",
            "Bot vẫn đang chạy; outcome các signal cũ vẫn được cập nhật tự động.",
        ]
        return "\n".join(lines)

    for index, row in enumerate(rows, 1):
        lines += [
            "",
            f"🔻 {index}. {row.get('symbol')} · {_tier_label(row.get('tier'))}",
            f"Entry: {_fmt(row.get('entry'))}",
            f"SL: {_fmt(row.get('stop'))} · 1.75 ATR",
            f"TP1: {_fmt(row.get('tp1'))} · 2 ATR | TP2: {_fmt(row.get('tp2'))} · 3 ATR",
            (
                f"D: ✅ Risk-Off + ✅ S4 Macro Bear | "
                f"Watch {row.get('watch_hours', '-')}h"
            ),
            (
                f"E1 EMA≥1.36ATR: {'✅' if row.get('e1_ema_gate') else '❌'} "
                f"({row.get('ema20_distance_atr', '-')})"
            ),
            (
                f"E2 Anti-bottom≥17: {'✅' if row.get('e2_anti_bottom_gate') else '❌'} "
                f"({row.get('anti_bottom_total', '-')})"
            ),
            (
                f"Market 4H/24H: {row.get('market_r4_pct', '-')}% / "
                f"{row.get('market_r24_pct', '-')}%"
            ),
            (
                f"Retest {row.get('retest_attempts', '-')} | "
                f"Bars below {row.get('bars_below', '-')}"
            ),
            f"Entry time VN: {_scan_time_vn(row.get('entry_time'))}",
        ]

    lines += [
        "",
        "Tier: A+=D+E1+E2 | A=D+E2 | B=D+E1 | C=D only",
        "⚠️ Live signal observation; không tự động đặt lệnh.",
    ]
    return "\n".join(lines)


def _send_text(token, chat_id, text):
    chunks = _split_text(text)
    for index, chunk in enumerate(chunks, 1):
        if len(chunks) > 1:
            chunk = f"[{index}/{len(chunks)}]\n" + chunk
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True},
            timeout=20,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Telegram send failed for {chat_id}: HTTP {response.status_code} {response.text[:500]}"
            )
    return len(chunks)


def send_telegram(report):
    token, chat_ids = _credentials()
    if not token or not chat_ids:
        return False

    text = build_text(report)
    messages = 0
    successes = 0
    failures = []

    for chat_id in chat_ids:
        try:
            sent = _send_text(token, chat_id, text)
            messages += sent
            successes += 1
            print(f"M2 Telegram destination OK: {chat_id} ({sent} message(s)).")
        except Exception as exc:
            failures.append({"chat_id": str(chat_id), "error": str(exc)})
            print(f"M2 Telegram destination FAILED: {chat_id}: {exc}")

    print(
        f"M2 live Telegram summary: {successes}/{len(chat_ids)} destination(s) OK "
        f"({messages} message(s)); failures={len(failures)}."
    )

    if successes == 0:
        raise RuntimeError(f"Telegram failed for all destinations: {failures}")
    return True
