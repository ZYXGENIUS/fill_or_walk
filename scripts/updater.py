from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


SOURCE_URL = "http://www.qiyoujiage.com/beijing.shtml"
SOURCE_NAME = "qiyoujiage.com (Beijing benchmark page)"
WINDOW_DAYS = 365

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "docs" / "data"
HISTORY_PATH = DATA_DIR / "history.json"
LATEST_PATH = DATA_DIR / "latest.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


@dataclass
class DailyPrice:
    date: str
    price: float


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_price(value: str) -> float:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", value)
    if not match:
        raise ValueError(f"Cannot parse numeric price from: {value!r}")
    return round(float(match.group(1)), 3)


def fetch_benchmark_92_price() -> float:
    response = requests.get(SOURCE_URL, headers=HEADERS, timeout=20)
    response.raise_for_status()
    response.encoding = "utf-8"

    soup = BeautifulSoup(response.text, "html.parser")
    for dt in soup.find_all("dt"):
        label = dt.get_text(strip=True)
        if "92#汽油" in label:
            dd = dt.find_next_sibling("dd")
            if dd:
                return parse_price(dd.get_text(" ", strip=True))

    fallback = re.search(
        r"92#汽油\s*</dt>\s*<dd>\s*([0-9]+(?:\.[0-9]+)?)\s*</dd>",
        response.text,
        flags=re.IGNORECASE,
    )
    if fallback:
        return round(float(fallback.group(1)), 3)

    raise RuntimeError("Cannot locate 92# benchmark price on source page.")


def normalize_history_entries(raw_entries: list[dict[str, Any]]) -> list[DailyPrice]:
    normalized: dict[str, float] = {}
    for item in raw_entries:
        day = item.get("date")
        price = item.get("price")
        if not isinstance(day, str):
            continue
        try:
            date.fromisoformat(day)
            numeric_price = round(float(price), 3)
        except (TypeError, ValueError):
            continue
        normalized[day] = numeric_price

    entries = [DailyPrice(date=d, price=p) for d, p in sorted(normalized.items())]
    return entries


def apply_window(entries: list[DailyPrice], today: date) -> list[DailyPrice]:
    cutoff = today - timedelta(days=WINDOW_DAYS - 1)
    filtered: list[DailyPrice] = []
    for item in entries:
        item_day = date.fromisoformat(item.date)
        if item_day >= cutoff:
            filtered.append(item)
    return filtered


def compute_metrics(entries: list[DailyPrice], today_price: float) -> dict[str, Any]:
    values = [item.price for item in entries]
    sample_size = len(values)

    lower_or_equal = sum(1 for value in values if value <= today_price)
    higher_or_equal = sum(1 for value in values if value >= today_price)

    price_percentile = round(lower_or_equal / sample_size * 100, 2)
    bargain_index = round(higher_or_equal / sample_size * 100, 2)

    decision = "WALK"
    decision_text = "Price is relatively high in the one-year window."
    if bargain_index >= 70:
        decision = "FILL"
        decision_text = "Price is in a favorable zone."
    elif bargain_index >= 40:
        decision = "HOLD"
        decision_text = "Price is in the middle zone."

    delta_from_previous = None
    if sample_size >= 2:
        previous_price = entries[-2].price
        delta_from_previous = round(today_price - previous_price, 3)

    return {
        "fuel_type": "92# gasoline",
        "benchmark": "Beijing",
        "unit": "CNY/L",
        "today_price": today_price,
        "window_days": WINDOW_DAYS,
        "sample_size": sample_size,
        "price_percentile": price_percentile,
        "bargain_index": bargain_index,
        "decision": decision,
        "decision_text": decision_text,
        "delta_from_previous": delta_from_previous,
    }


def main() -> None:
    now_cn = datetime.now(ZoneInfo("Asia/Shanghai"))
    today_str = now_cn.date().isoformat()

    today_price = fetch_benchmark_92_price()

    history = load_json(
        HISTORY_PATH,
        {
            "meta": {
                "fuel_type": "92# gasoline",
                "benchmark": "Beijing",
                "unit": "CNY/L",
                "source_name": SOURCE_NAME,
                "source_url": SOURCE_URL,
                "window_days": WINDOW_DAYS,
            },
            "prices": [],
        },
    )

    entries = normalize_history_entries(history.get("prices", []))

    by_day = {item.date: item for item in entries}
    by_day[today_str] = DailyPrice(date=today_str, price=today_price)
    entries = [by_day[key] for key in sorted(by_day.keys())]
    entries = apply_window(entries, now_cn.date())

    history_payload = {
        "meta": {
            "fuel_type": "92# gasoline",
            "benchmark": "Beijing",
            "unit": "CNY/L",
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "window_days": WINDOW_DAYS,
            "updated_at": now_cn.isoformat(timespec="seconds"),
        },
        "prices": [asdict(item) for item in entries],
    }

    metrics = compute_metrics(entries, today_price)
    latest_payload = {
        "updated_at": now_cn.isoformat(timespec="seconds"),
        "source": {
            "name": SOURCE_NAME,
            "url": SOURCE_URL,
        },
        "metric": metrics,
        "history_tail": [asdict(item) for item in entries[-30:]],
    }

    write_json(HISTORY_PATH, history_payload)
    write_json(LATEST_PATH, latest_payload)

    print("Updated fuel index data successfully.")
    print(f"Date: {today_str}")
    print(f"Price: {today_price:.3f} CNY/L")
    print(f"Bargain Index: {metrics['bargain_index']:.2f}")


if __name__ == "__main__":
    main()
