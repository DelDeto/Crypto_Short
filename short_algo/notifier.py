import os
from datetime import datetime, timedelta, timezone

import requests

# Same shared group used by Market-Setup-Watch.
DEFAULT_GROUP_CHAT_ID = "-1003984243045"
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
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    personal_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    group_chat_id = os.getenv("TELEGRAM_GROUP_CHAT_ID") or DEFAULT_GROUP_CHAT_ID

    if not token:
        print("Telegram skipped: missing TELEGRAM_BOT_TOKEN.")
        return None, []

    chat_ids = []
    for chat_id in (personal_chat_id, group_chat_id):
        if chat_id and chat_id not in chat_ids:
            chat_ids.append(chat_id)

    if not chat_ids:
        print("Telegram skipped: no destination configured.")
        return None, []

    return token, chat_ids


def _split_text(text, max_chars=3800):
    if len(text) <= max_chars:
        return [text]

    chunks = []
    current = []
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
            start = 0
            while start < len(block):
                chunks.append(block[start:start + max_chars])
                start += max_chars
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def build_text(report, max_rows=8):
    rows = [
        row for row in report.get("results", [])
        if row.get("status") in ("ENTRY_READY", "DEVELOPING", "WATCH")
    ][:max_rows]

    counts = report.get("status_counts", {})
    lines = [
        "🔻 CRYPTO SHORT SCANNER",
        "=" * 28,
        f"Scan VN: {_scan_time_vn(report.get('finished_at'))}",
        (
            f"MEXC: {report.get('universe_count', 0)} | "
            f"Fast: {report.get('fast_success', 0)} | "
            f"Deep: {report.get('deep_success', 0)}"
        ),
        (
            f"🔥 ENTRY {counts.get('ENTRY_READY', 0)} | "
            f"⚡ DEVELOPING {counts.get('DEVELOPING', 0)} | "
            f"👀 WATCH {counts.get('WATCH', 0)}"
        ),
        "Rule: TP1 = 2R | TP2 = 3R | Runner = 5R",
    ]

    if not rows:
        lines += [
            "",
            "Chưa có setup Short đạt ngưỡng WATCH trở lên.",
        ]
        return "\n".join(lines)

    icons = {
        "ENTRY_READY": "🔥",
        "DEVELOPING": "⚡",
        "WATCH": "👀",
    }

    for index, row in enumerate(rows, 1):
        reasons = ", ".join(row.get("reasons") or ["-"])
        filters = row.get("filters") or {}
        lines += [
            "",
            (
                f"{icons.get(row.get('status'), '•')} {index}. "
                f"{row.get('symbol')} · SHORT · "
                f"{row.get('status')} · S{row.get('score')}/100"
            ),
            f"Entry: {_fmt(row.get('entry'))}",
            (
                f"SL: {_fmt(row.get('stop'))} "
                f"({row.get('stop_pct', '-')}%)"
            ),
            (
                f"TP1: {_fmt(row.get('tp1'))} (2R) | "
                f"TP2: {_fmt(row.get('tp2'))} (3R)"
            ),
            f"Runner: {_fmt(row.get('runner'))} (5R)",
            (
                f"Room→support: {row.get('support_room_r', '-')}R | "
                f"ATR 1H: {row.get('atr_pct_1h', '-')}%"
            ),
            (
                f"24H: {row.get('ticker_change_24h_pct', '-')}% | "
                f"Funding: {row.get('funding_rate', '-')}"
            ),
            (
                "Filter: "
                f"MTF={'Y' if filters.get('mtf_ok') else 'N'} | "
                f"Trigger={'Y' if filters.get('trigger_present') else 'N'} | "
                f"Location={'Y' if filters.get('location_ok') else 'N'} | "
                f"Risk={'Y' if filters.get('risk_ok') else 'N'}"
            ),
            f"Why: {reasons}",
        ]

    lines += [
        "",
        "⚠️ Scanner research signal — không phải auto-order.",
    ]
    return "\n".join(lines)


def _send_text(token, chat_id, text):
    chunks = _split_text(text)
    for index, chunk in enumerate(chunks, 1):
        if len(chunks) > 1:
            chunk = f"[{index}/{len(chunks)}]\n" + chunk
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Telegram send failed for {chat_id}: "
                f"HTTP {response.status_code} {response.text[:500]}"
            )
    return len(chunks)


def send_telegram(report):
    token, chat_ids = _credentials()
    if not token or not chat_ids:
        return False

    text = build_text(report)
    messages = 0
    for chat_id in chat_ids:
        messages += _send_text(token, chat_id, text)

    print(
        f"Crypto Short Telegram sent to {len(chat_ids)} destination(s) "
        f"({messages} message(s))."
    )
    return True
