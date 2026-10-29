"""IST <-> HND bayram uçuş fiyat takipçisi.

Her çalıştırmada bayramı (arife dahil) tamamen kapsayan tüm gidiş-dönüş
kombinasyonlarını Google Flights üzerinden tarar ve sonuçları
docs/data.json dosyasına ekler. Panel (docs/index.html) bu dosyayı okur.
"""

import json
import random
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fast_flights import FlightQuery, Passengers, create_query, fetch_flights_html
from selectolax.lexbor import LexborHTMLParser

ROOT = Path(__file__).parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
DATA_FILE = ROOT / "docs" / "data.json"


def combinations():
    """Bayramın ilk gününden (arife) önce/aynı gün gidip son gününden sonra/aynı gün dönen kombinasyonlar."""
    today = date.today()
    for h in CONFIG["holidays"]:
        first = date.fromisoformat(h["first_day"])
        last = date.fromisoformat(h["last_day"])
        for days in range(CONFIG["min_days"], CONFIG["max_days"] + 1):
            dep = last - timedelta(days=days)
            while dep <= first:
                ret = dep + timedelta(days=days)
                if dep > today:
                    yield h["id"], dep, ret, days
                dep += timedelta(days=1)


def build_query(dep, ret, max_stops):
    o, d = CONFIG["origin"], CONFIG["destination"]
    return create_query(
        flights=[
            FlightQuery(date=dep.isoformat(), from_airport=o, to_airport=d),
            FlightQuery(date=ret.isoformat(), from_airport=d, to_airport=o),
        ],
        trip="round-trip",
        seat="economy",
        passengers=Passengers(adults=CONFIG["adults"]),
        language="tr",
        currency=CONFIG["currency"],
        max_stops=max_stops,
    )


def parse(html):
    """Google Flights sayfasından gidiş seçeneklerini ve gidiş-dönüş toplam fiyatlarını çıkarır.

    fast-flights'ın kendi ayrıştırıcısı fiyatsız sonuçlarda çöktüğü ve sadece
    "en iyi uçuşlar" bloğunu okuduğu için burada kendi ayrıştırıcımızı kullanıyoruz.
    """
    node = LexborHTMLParser(html).css_first(r"script.ds\:1")
    if node is None:
        raise RuntimeError("Google Flights beklenen veriyi döndürmedi (engellenmiş olabilir)")
    js = node.text()
    raw = js.split("data:", 1)[1].rsplit(",", 1)[0]
    if raw.endswith("errorHasStatus: true"):
        return []
    payload = json.loads(raw)

    options = []
    for block in (2, 3):
        rows = payload[block][0] if len(payload) > block and payload[block] else None
        for row in rows or []:
            try:
                price = row[1][0][1]
            except (IndexError, TypeError):
                continue
            if not price:
                continue
            flight = row[0]
            legs = []
            for s in flight[2]:
                dep_t = (s[8] or []) + [None, None]
                arr_t = (s[10] or []) + [None, None]
                legs.append({
                    "from": s[3],
                    "to": s[6],
                    "dep": f"{dep_t[0] or 0:02d}:{dep_t[1] or 0:02d}",
                    "arr": f"{arr_t[0] or 0:02d}:{arr_t[1] or 0:02d}",
                    "arr_date": "-".join(f"{x:02d}" for x in s[21]) if s[21] else None,
                    "minutes": s[11],
                })
            options.append({
                "price": int(price),
                "airlines": flight[1],
                "legs": legs,
                "minutes": flight[9] if len(flight) > 9 and isinstance(flight[9], int) else None,
            })
    options.sort(key=lambda x: x["price"])
    return options


def fetch(dep, ret, max_stops, attempts=3):
    q = build_query(dep, ret, max_stops)
    for i in range(attempts):
        try:
            return parse(fetch_flights_html(q)), q.url()
        except Exception as e:  # ağ hatası, engelleme, değişen sayfa yapısı
            err = e
            time.sleep(5 * (i + 1) + random.random() * 3)
    raise err


def summarize(direct_opts, conn_opts):
    direct = next((o for o in direct_opts if len(o["legs"]) == 1), None)
    conn = [o for o in conn_opts if len(o["legs"]) == 2]
    return direct, conn[:3]


def load_data():
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return {"runs": [], "combos": {}}


def compact_option(o):
    if not o:
        return None
    return {
        "price": o["price"],
        "airlines": o["airlines"],
        "via": [leg["to"] for leg in o["legs"][:-1]],
        "legs": o["legs"],
        "minutes": o["minutes"],
    }


def main():
    data = load_data()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["runs"].append(now)
    run_idx = len(data["runs"]) - 1
    combos = list(combinations())
    ok = failed = 0

    for n, (hid, dep, ret, days) in enumerate(combos, 1):
        key = f"{dep.isoformat()}_{ret.isoformat()}"
        try:
            direct_opts, direct_url = fetch(dep, ret, 0)
            time.sleep(1 + random.random() * 2)
            conn_opts, conn_url = fetch(dep, ret, 1)
            time.sleep(1 + random.random() * 2)
        except Exception as e:
            failed += 1
            print(f"[{n}/{len(combos)}] {key} HATA: {e}", file=sys.stderr)
            continue

        direct, conn = summarize(direct_opts, conn_opts)
        entry = data["combos"].setdefault(key, {
            "holiday": hid, "dep": dep.isoformat(), "ret": ret.isoformat(),
            "days": days, "history": [],
        })
        point = [run_idx, direct["price"] if direct else None, conn[0]["price"] if conn else None]
        # Sadece fiyat değiştiğinde yeni nokta ekle; dosya küçük kalsın.
        if not entry["history"] or entry["history"][-1][1:] != point[1:]:
            entry["history"].append(point)
        entry["checked"] = run_idx
        entry["direct"] = compact_option(direct)
        entry["connecting"] = [compact_option(c) for c in conn]
        entry["urls"] = {"direct": direct_url, "connecting": conn_url}
        ok += 1
        print(f"[{n}/{len(combos)}] {key} aktarmasız={point[1]} aktarmalı={point[2]}")

    data["updated"] = now
    data["config"] = CONFIG
    data["last_run"] = {"at": now, "ok": ok, "failed": failed, "total": len(combos)}
    DATA_FILE.parent.mkdir(exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Bitti: {ok} başarılı, {failed} hatalı / {len(combos)}")
    # Hepsi başarısızsa iş akışı kırmızı görünsün.
    sys.exit(1 if ok == 0 and combos else 0)


if __name__ == "__main__":
    main()
