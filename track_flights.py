"""
Flight Price Tracker: MSP <-> ANC Round Trip
Uses fast-flights (v3) to scrape Google Flights pricing.
Extracts Google's embedded price history (~60 days) and price insight label.
Logs prices to CSV for ongoing tracking.

Designed to run via GitHub Actions on a cron schedule.

Usage:
    python track_flights.py              # Run once, print + log results
    python track_flights.py --history    # Show price history from CSV
    python track_flights.py --google-history  # Show Google's ~60-day embedded history
"""

import csv
import sys
import time
from datetime import datetime
from pathlib import Path

import rjsonc
from selectolax.lexbor import LexborHTMLParser
from fast_flights import FlightQuery, Passengers, create_query, get_flights, fetch_flights_html

# ============================================================
# CONFIGURATION
# ============================================================
DEPART_DATE = "2026-07-11"      # MSP -> ANC (Saturday)
RETURN_DATE = "2026-07-17"      # ANC -> MSP (Thursday)
FROM_AIRPORT = "MSP"
TO_AIRPORT = "ANC"
ADULTS = 1
SEAT = "economy"
CURRENCY = "USD"

DATA_DIR = Path(__file__).parent / "data"
CSV_FILE = DATA_DIR / "price_history.csv"

# ============================================================


def extract_price_insight(html):
    """Extract price insight label and historical prices from Google Flights HTML.

    Google embeds ~60 days of daily cheapest prices in a JS data blob (data[5]),
    plus a price level label (low/typical/high) in a span.gOatQ element.
    """
    parser = LexborHTMLParser(html)
    result = {"label": "", "current_price": None, "history": []}

    label_node = parser.css_first("span.gOatQ")
    if label_node:
        result["label"] = label_node.text(strip=True)

    try:
        script = parser.css_first(r"script.ds\:1")
        if not script:
            return result
        js = script.text()
        json_str = js.split("data:", 1)[1].rsplit(",", 1)[0]
        data = rjsonc.loads(json_str)

        d5 = data[5]
        if d5 and len(d5) > 1 and d5[1] and len(d5[1]) > 1:
            result["current_price"] = d5[1][1]

        if len(d5) > 10 and d5[10] and len(d5[10]) > 0:
            for ts_ms, price in d5[10][0]:
                dt = datetime.fromtimestamp(ts_ms / 1000)
                result["history"].append((dt.strftime("%Y-%m-%d"), price))
    except Exception as e:
        print("  Warning: Could not parse price insight data: %s" % e)

    return result


def fetch_with_insight(date, from_apt, to_apt):
    """Fetch flights AND extract price insight/history for a leg."""
    query = create_query(
        flights=[FlightQuery(date=date, from_airport=from_apt, to_airport=to_apt)],
        seat=SEAT,
        trip="one-way",
        passengers=Passengers(adults=ADULTS),
        currency=CURRENCY,
    )
    html = fetch_flights_html(query)

    from fast_flights.parser import parse
    flights = parse(html)
    insight = extract_price_insight(html)

    return flights, insight


def format_flight(f):
    """Format a single Flights object into a readable string."""
    try:
        dep_t = f.flights[0].departure.time
        arr_t = f.flights[-1].arrival.time
        dep = "%02d:%02d" % (dep_t[0], dep_t[1]) if len(dep_t) >= 2 else str(dep_t)
        arr = "%02d:%02d" % (arr_t[0], arr_t[1]) if len(arr_t) >= 2 else str(arr_t)
    except Exception:
        dep, arr = "??:??", "??:??"

    airlines = ", ".join(f.airlines)
    stops = len(f.flights) - 1
    total_min = sum(s.duration for s in f.flights)
    return "$%d | %s | %s->%s | %dh%02dm | %d stop(s)" % (
        f.price, airlines, dep, arr, total_min // 60, total_min % 60, stops
    )


def log_to_csv(timestamp, outbound, inbound, out_insight, in_insight):
    """Append current cheapest prices to the CSV log."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    file_exists = CSV_FILE.exists()

    out_sorted = sorted(outbound, key=lambda x: x.price)
    in_sorted = sorted(inbound, key=lambda x: x.price)

    ob = out_sorted[0] if out_sorted else None
    ib = in_sorted[0] if in_sorted else None

    fieldnames = [
        "timestamp", "depart_date", "return_date",
        "out_cheapest_price", "out_cheapest_airline", "out_cheapest_stops",
        "out_num_options", "out_price_label",
        "in_cheapest_price", "in_cheapest_airline", "in_cheapest_stops",
        "in_num_options", "in_price_label",
        "roundtrip_cheapest_total",
        "out_cheapest_nonstop", "out_nonstop_airline",
        "in_cheapest_nonstop", "in_nonstop_airline",
    ]

    row = {
        "timestamp": timestamp,
        "depart_date": DEPART_DATE,
        "return_date": RETURN_DATE,
        "out_cheapest_price": ob.price if ob else "",
        "out_cheapest_airline": ", ".join(ob.airlines) if ob else "",
        "out_cheapest_stops": len(ob.flights) - 1 if ob else "",
        "out_num_options": len(outbound),
        "out_price_label": out_insight["label"],
        "in_cheapest_price": ib.price if ib else "",
        "in_cheapest_airline": ", ".join(ib.airlines) if ib else "",
        "in_cheapest_stops": len(ib.flights) - 1 if ib else "",
        "in_num_options": len(inbound),
        "in_price_label": in_insight["label"],
        "roundtrip_cheapest_total": (ob.price + ib.price) if (ob and ib) else "",
        "out_cheapest_nonstop": "",
        "out_nonstop_airline": "",
        "in_cheapest_nonstop": "",
        "in_nonstop_airline": "",
    }

    out_nonstop = [f for f in out_sorted if len(f.flights) == 1]
    in_nonstop = [f for f in in_sorted if len(f.flights) == 1]
    if out_nonstop:
        row["out_cheapest_nonstop"] = out_nonstop[0].price
        row["out_nonstop_airline"] = ", ".join(out_nonstop[0].airlines)
    if in_nonstop:
        row["in_cheapest_nonstop"] = in_nonstop[0].price
        row["in_nonstop_airline"] = ", ".join(in_nonstop[0].airlines)

    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def save_google_history(out_insight, in_insight):
    """Save Google's embedded price history to CSV files."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    for label, insight, from_apt, to_apt, date in [
        ("outbound", out_insight, FROM_AIRPORT, TO_AIRPORT, DEPART_DATE),
        ("return", in_insight, TO_AIRPORT, FROM_AIRPORT, RETURN_DATE),
    ]:
        if not insight["history"]:
            continue
        csv_path = DATA_DIR / ("google_history_%s.csv" % label)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "cheapest_price", "route", "travel_date"])
            route = "%s->%s" % (from_apt, to_apt)
            for date_str, price in insight["history"]:
                writer.writerow([date_str, price, route, date])


def print_results(outbound, inbound, out_insight, in_insight):
    """Print summary of current prices."""
    print("")
    print("=" * 70)
    print("FLIGHT PRICES: %s <-> %s" % (FROM_AIRPORT, TO_AIRPORT))
    print("  Outbound: %s  |  Return: %s" % (DEPART_DATE, RETURN_DATE))
    print("  Checked: %s UTC" % datetime.now(tz=__import__('datetime').timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 70)

    for label, insight in [("OUTBOUND", out_insight), ("RETURN", in_insight)]:
        if insight["label"]:
            price_str = "  %s price level: %s" % (label, insight["label"].upper())
            if insight["history"]:
                prices = [p for _, p in insight["history"]]
                price_str += " (range: $%d-$%d over %d days)" % (
                    min(prices), max(prices), len(prices)
                )
            print(price_str)

    out_sorted = sorted(outbound, key=lambda x: x.price)
    in_sorted = sorted(inbound, key=lambda x: x.price)

    print("\nOUTBOUND %s -> %s (%d options):" % (FROM_AIRPORT, TO_AIRPORT, len(outbound)))
    print("-" * 60)
    for f in out_sorted[:10]:
        print("  " + format_flight(f))

    print("\nRETURN %s -> %s (%d options):" % (TO_AIRPORT, FROM_AIRPORT, len(inbound)))
    print("-" * 60)
    for f in in_sorted[:10]:
        print("  " + format_flight(f))

    if out_sorted and in_sorted:
        best_out = out_sorted[0]
        best_in = in_sorted[0]
        print("\nBEST ROUND-TRIP COMBO:")
        print("  Out: " + format_flight(best_out))
        print("  Ret: " + format_flight(best_in))
        print("  TOTAL: $%d" % (best_out.price + best_in.price))

        out_nonstop = [f for f in out_sorted if len(f.flights) == 1]
        in_nonstop = [f for f in in_sorted if len(f.flights) == 1]
        if out_nonstop and in_nonstop:
            print("\nBEST NONSTOP ROUND-TRIP:")
            print("  Out: " + format_flight(out_nonstop[0]))
            print("  Ret: " + format_flight(in_nonstop[0]))
            print("  TOTAL: $%d" % (out_nonstop[0].price + in_nonstop[0].price))

    print("")


def show_history():
    """Display price history from CSV log."""
    if not CSV_FILE.exists():
        print("No history yet. Run the tracker first.")
        return

    print("\nPRICE HISTORY: %s <-> %s" % (FROM_AIRPORT, TO_AIRPORT))
    print("=" * 100)
    print("%-20s | %-8s | %-6s | %-8s | %-6s | %-10s | %-15s | %-15s" % (
        "Timestamp", "Out $", "Label", "Ret $", "Label", "RT Total", "Out Airline", "Ret Airline"
    ))
    print("-" * 100)

    with open(CSV_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            print("%-20s | $%-7s | %-6s | $%-7s | %-6s | $%-9s | %-15s | %-15s" % (
                row["timestamp"],
                row["out_cheapest_price"],
                row.get("out_price_label", "")[:6],
                row["in_cheapest_price"],
                row.get("in_price_label", "")[:6],
                row["roundtrip_cheapest_total"],
                row["out_cheapest_airline"][:15],
                row["in_cheapest_airline"][:15],
            ))
    print("")


def show_google_history():
    """Fetch and display Google's embedded ~60-day price history."""
    print("\nFetching Google's embedded price history...\n")

    for label, date, from_apt, to_apt in [
        ("OUTBOUND", DEPART_DATE, FROM_AIRPORT, TO_AIRPORT),
        ("RETURN", RETURN_DATE, TO_AIRPORT, FROM_AIRPORT),
    ]:
        query = create_query(
            flights=[FlightQuery(date=date, from_airport=from_apt, to_airport=to_apt)],
            seat=SEAT, trip="one-way", passengers=Passengers(adults=ADULTS), currency=CURRENCY,
        )
        html = fetch_flights_html(query)
        insight = extract_price_insight(html)

        print("%s (%s -> %s on %s):" % (label, from_apt, to_apt, date))
        if insight["label"]:
            print("  Current price level: %s" % insight["label"].upper())
        if insight["history"]:
            prices = [p for _, p in insight["history"]]
            print("  History: %d days (%s to %s)" % (
                len(insight["history"]), insight["history"][0][0], insight["history"][-1][0],
            ))
            print("  Range: $%d - $%d" % (min(prices), max(prices)))
            print("  " + "-" * 35)
            for date_str, price in insight["history"]:
                print("  %s  $%d" % (date_str, price))
        else:
            print("  No history data available")
        print("")


def run_once():
    """Single price check with insight extraction."""
    timestamp = datetime.now(tz=__import__('datetime').timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    print("Fetching outbound %s -> %s on %s..." % (FROM_AIRPORT, TO_AIRPORT, DEPART_DATE))
    outbound, out_insight = fetch_with_insight(DEPART_DATE, FROM_AIRPORT, TO_AIRPORT)

    print("Fetching return %s -> %s on %s..." % (TO_AIRPORT, FROM_AIRPORT, RETURN_DATE))
    inbound, in_insight = fetch_with_insight(RETURN_DATE, TO_AIRPORT, FROM_AIRPORT)

    print_results(outbound, inbound, out_insight, in_insight)
    log_to_csv(timestamp, outbound, inbound, out_insight, in_insight)
    save_google_history(out_insight, in_insight)
    print("Logged to: %s" % CSV_FILE)


def main():
    if "--history" in sys.argv:
        show_history()
    elif "--google-history" in sys.argv:
        show_google_history()
    else:
        run_once()


if __name__ == "__main__":
    main()
