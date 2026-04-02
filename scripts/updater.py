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

EASTMONEY_API_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EASTMONEY_SOURCE_NAME = "Eastmoney datacenter oil reports"
EASTMONEY_DATE_REPORT = "RPTA_WEB_YJ_RQ"
EASTMONEY_CITY_REPORT = "RPTA_WEB_YJ_JH"
BENCHMARK_CITY_CN = "\u5317\u4eac"

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


def eastmoney_request(params: dict[str, Any]) -> dict[str, Any]:
    response = requests.get(EASTMONEY_API_URL, params=params, headers=HEADERS, timeout=20)
    response.raise_for_status()

    payload = response.json()
    if not payload.get("success"):
        message = payload.get("message", "unknown error")
        raise RuntimeError(f"Eastmoney API error: {message}")

    return payload


def fetch_adjustment_dates(max_rows: int = 300) -> list[date]:
    payload = eastmoney_request(
        {
            "reportName": EASTMONEY_DATE_REPORT,
            "columns": "ALL",
            "sortColumns": "DIM_DATE",
            "sortTypes": -1,
            "pageNumber": 1,
            "pageSize": max_rows,
            "source": "WEB",
        }
    )

    rows = (payload.get("result") or {}).get("data") or []
    parsed: set[date] = set()
    for row in rows:
        raw_day = str(row.get("DIM_DATE", ""))[:10]
        if not raw_day:
            continue
        try:
            parsed.add(date.fromisoformat(raw_day))
        except ValueError:
            continue

    return sorted(parsed)


def fetch_beijing_92_on_adjust_date(adjust_day: date) -> float | None:
    payload = eastmoney_request(
        {
            "reportName": EASTMONEY_CITY_REPORT,
            "columns": "ALL",
            "filter": f"(DIM_DATE='{adjust_day.isoformat()}')",
            "sortColumns": "FIRST_LETTER",
            "sortTypes": 1,
            "pageNumber": 1,
            "pageSize": 200,
            "source": "WEB",
        }
    )

    rows = (payload.get("result") or {}).get("data") or []
    for row in rows:
        city_name = str(row.get("CITYNAME", ""))
        if city_name != BENCHMARK_CITY_CN:
            continue
        value = row.get("V92")
        if value is None:
            return None
        try:
            return round(float(value), 3)
        except (TypeError, ValueError):
            return None

    return None


def date_range(start: date, end: date) -> list[date]:
    total = (end - start).days
    return [start + timedelta(days=offset) for offset in range(total + 1)]


def build_bootstrap_daily_history(today: date) -> list[DailyPrice]:
    start_day = today - timedelta(days=WINDOW_DAYS - 1)

    adjust_days = [day for day in fetch_adjustment_dates() if day <= today]
    if not adjust_days:
        return []

    anchor_candidates = [day for day in adjust_days if day <= start_day]
    anchor_day = max(anchor_candidates) if anchor_candidates else adjust_days[0]

    needed_days = sorted({anchor_day, *[day for day in adjust_days if day >= start_day]})
    price_points: list[tuple[date, float]] = []

    for day in needed_days:
        try:
            price = fetch_beijing_92_on_adjust_date(day)
        except Exception as exc:  # pragma: no cover - network edge case
            print(f"Warning: failed to fetch adjustment price for {day.isoformat()}: {exc}")
            continue
        if price is None:
            continue
        price_points.append((day, price))

    if not price_points:
        return []

    price_points.sort(key=lambda item: item[0])
    point_idx = 0
    current_price = price_points[0][1]

    output: list[DailyPrice] = []
    for day in date_range(start_day, today):
        while point_idx + 1 < len(price_points) and price_points[point_idx + 1][0] <= day:
            point_idx += 1
            current_price = price_points[point_idx][1]
        output.append(DailyPrice(date=day.isoformat(), price=round(current_price, 3)))

    return output


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


def percentile_rank(values: list[float], price: float) -> float | None:
    if not values:
        return None
    lower_or_equal = sum(1 for value in values if value <= price)
    return round(lower_or_equal / len(values) * 100, 2)


def values_in_period(entries: list[DailyPrice], start_day: date, end_day: date) -> list[float]:
    values: list[float] = []
    for item in entries:
        item_day = date.fromisoformat(item.date)
        if start_day <= item_day <= end_day:
            values.append(item.price)
    return values


def compute_period_percentiles(entries: list[DailyPrice], today_price: float, today: date) -> dict[str, Any]:
    month_start = today.replace(day=1)
    quarter_start_month = ((today.month - 1) // 3) * 3 + 1
    quarter_start = date(today.year, quarter_start_month, 1)

    period_defs = {
        "past_30_days": {
            "label": "过去30天",
            "start": today - timedelta(days=29),
        },
        "this_month": {
            "label": "本月",
            "start": month_start,
        },
        "this_quarter": {
            "label": "本季度",
            "start": quarter_start,
        },
        "past_120_days": {
            "label": "过去120天",
            "start": today - timedelta(days=119),
        },
    }

    result: dict[str, Any] = {}
    for key, config in period_defs.items():
        values = values_in_period(entries, config["start"], today)
        result[key] = {
            "label": config["label"],
            "value": percentile_rank(values, today_price),
            "sample_size": len(values),
        }

    return result


def compute_metrics(entries: list[DailyPrice], today_price: float, today: date) -> dict[str, Any]:
    values = [item.price for item in entries]
    sample_size = len(values)

    if sample_size == 0:
        raise RuntimeError("No history entries available for metric calculation.")

    lower_or_equal = sum(1 for value in values if value <= today_price)
    higher_or_equal = sum(1 for value in values if value >= today_price)

    price_percentile = round(lower_or_equal / sample_size * 100, 2)
    bargain_index = round(higher_or_equal / sample_size * 100, 2)

    decision = "WALK"
    decision_zh = "建议观望"
    decision_text = "当前价格处于近一年相对高位，建议观望。"
    if bargain_index >= 70:
        decision = "FILL"
        decision_zh = "建议加油"
        decision_text = "当前价格处于近一年相对低位，建议加油。"
    elif bargain_index >= 40:
        decision = "HOLD"
        decision_zh = "按需加油"
        decision_text = "当前价格处于中位区间，可按需补能。"

    delta_from_previous = None
    if sample_size >= 2:
        previous_price = entries[-2].price
        delta_from_previous = round(today_price - previous_price, 3)

    period_percentiles = compute_period_percentiles(entries, today_price, today)

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
        "decision_zh": decision_zh,
        "decision_text": decision_text,
        "decision_text_zh": decision_text,
        "delta_from_previous": delta_from_previous,
        "period_percentiles": period_percentiles,
    }


def main() -> None:
    now_cn = datetime.now(ZoneInfo("Asia/Shanghai"))
    today_str = now_cn.date().isoformat()

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

    bootstrap_used = False
    if len(entries) < WINDOW_DAYS:
        try:
            bootstrap_entries = build_bootstrap_daily_history(now_cn.date())
            if bootstrap_entries:
                bootstrap_used = True
                merged_by_day = {item.date: item for item in bootstrap_entries}
                for item in entries:
                    merged_by_day[item.date] = item
                entries = [merged_by_day[key] for key in sorted(merged_by_day.keys())]
        except Exception as exc:  # pragma: no cover - network edge case
            print(f"Warning: failed to bootstrap one-year history: {exc}")

    try:
        today_price = fetch_benchmark_92_price()
    except Exception as exc:
        if entries:
            today_price = entries[-1].price
            print(f"Warning: live benchmark fetch failed, fallback to last known price: {exc}")
        else:
            raise

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
            "bootstrap_source": EASTMONEY_SOURCE_NAME,
            "bootstrap_used": bootstrap_used,
        },
        "prices": [asdict(item) for item in entries],
    }

    metrics = compute_metrics(entries, today_price, now_cn.date())
    latest_payload = {
        "updated_at": now_cn.isoformat(timespec="seconds"),
        "source": {
            "name": SOURCE_NAME,
            "url": SOURCE_URL,
        },
        "metric": metrics,
        "history_status": {
            "sample_size": len(entries),
            "bootstrap_used": bootstrap_used,
        },
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
