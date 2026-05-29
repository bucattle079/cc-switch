from __future__ import annotations

from pathlib import Path


SKILL = Path(r"C:\Users\Admin\.codex\skills\vela-daily-briefing\SKILL.md")


def main() -> int:
    text = SKILL.read_text(encoding="utf-8")
    old_window = (
        "Default time window: China time, previous calendar night. For China date `D`, "
        "use `D-1 18:00` through `D 09:00` as the standard A-share premarket window; if the user "
        "asks before 08:00, use `D-1 18:00` through the current time. If the user asks "
        "later in the day, still use the most recent completed overnight window unless "
        "they explicitly ask for a live refresh. State the exact window."
    )
    new_window = (
        "Default time windows are Beijing time and depend on when the user asks:\n\n"
        "- Before 12:30: use the 09:00 cache window, `D-1 18:00` to `D 09:00`; describe A股盘前, 前夜美股, 人民币, 港股联动.\n"
        "- From 12:30 through before 17:00: use the 12:30 cache window, `D 09:00` to `D 12:30`; describe A股午盘后 and 日韩盘中, not 日韩收盘.\n"
        "- At or after 17:00: use the 17:00 cache window, `D 09:00` to `D 17:00`; use 美股盘前, futures, 10Y US Treasury, dollar, AI leader risk.\n\n"
        "Always state the exact Beijing-time window."
    )
    if old_window in text:
        text = text.replace(old_window, new_window)

    old_markets = (
        "- Financial markets: Bloomberg, Wall Street Journal, Financial Times, CNBC, "
        "MarketWatch, central banks, exchanges, company filings."
    )
    new_markets = (
        "- Financial markets: emphasize US equities, A-shares, South Korea, and Japan. "
        "Track S&P 500, Nasdaq, Dow, US futures, US Treasury yields, dollar, Shanghai Composite, "
        "Shenzhen Component, ChiNext, CSI 300, yuan, KOSPI, won, Samsung/SK Hynix, Nikkei, TOPIX, yen, BOJ, "
        "plus Bloomberg, Wall Street Journal, Financial Times, CNBC, MarketWatch, central banks, exchanges, and filings."
    )
    if old_markets in text:
        text = text.replace(old_markets, new_markets)

    old_judgment = (
        "- market implication;\n"
        "- technology/AI implication;\n"
        "- what to watch in the next 12-24 hours."
    )
    current_judgment = (
        "- market implication;\n"
        "- A-share implication;\n"
        "- US equity implication;\n"
        "- technology/AI implication;\n"
        "- what to watch in the next 12-24 hours."
    )
    new_judgment = (
        "- market implication;\n"
        "- A-share implication;\n"
        "- US equity implication;\n"
        "- Japan/South Korea equity implication;\n"
        "- technology/AI implication;\n"
        "- what to watch in the next 12-24 hours."
    )
    if old_judgment in text:
        text = text.replace(old_judgment, new_judgment)
    if current_judgment in text:
        text = text.replace(current_judgment, new_judgment)

    old_item_rule = (
        "Each item must include the core fact, why it matters, and a compact source label. "
        "If Bloomberg or WSJ is paywalled, use accessible headline/snippet plus at least one accessible corroborating source. "
        "Do not fabricate details behind paywalls. For major claims, cross-check with at least two sources when available."
    )
    new_item_rule = (
        "Each numbered item should be primarily Chinese and should include only the core fact plus a compact source label. "
        "Do not append repetitive per-item templates such as `意义：...`; analysis belongs in `VELA 判断` at the end. "
        "If Bloomberg or WSJ is paywalled, use accessible headline/snippet plus at least one accessible corroborating source. "
        "Do not fabricate details behind paywalls. For major claims, cross-check with at least two sources when available."
    )
    if old_item_rule in text:
        text = text.replace(old_item_rule, new_item_rule)

    text = text.replace(
        "1. 标题 — 发生了什么；为什么重要。来源：Reuters / 官方声明",
        "1. 中文核心事实。来源：Reuters / 官方声明",
    )

    SKILL.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
