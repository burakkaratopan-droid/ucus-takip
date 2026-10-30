"""IST <-> Japonya (Haneda, Narita, Kansai) bayram uçuş fiyat takipçisi.

Her çalıştırmada bayramı (arife dahil) tamamen kapsayan tüm gidiş-dönüş
kombinasyonlarını Google Flights üzerinden tarar ve sonuçları
docs/data.json dosyasına ekler. Panel (docs/index.html) bu dosyayı okur.
"""

import json
import os
import random
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fast_flights import FlightQuery, Passengers, create_query, fetch_flights_html
from selectolax.lexbor import LexborHTMLParser

ROOT = Path(__file__).parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
DATA_FILE = ROOT / "docs" / "data.json"


def destinations():
    """config.json'daki varış havalimanı kodları (eski tek 'destination' ayarı da desteklenir)."""
    if "destinations" in CONFIG:
        return [d["code"] for d in CONFIG["destinations"]]
    return [CONFIG["destination"]]


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
                    for dest in destinations():
                        yield dest, h["id"], dep, ret, days
                dep += timedelta(days=1)


def build_query(dest, dep, ret, max_stops, safe=False):
    # "NRT-KIX" gibi kodlar açık çene rotasıdır: NRT'ye gidiş, KIX'ten dönüş (çoklu şehir araması).
    o = CONFIG["origin"]
    out_to, back_from = dest.split("-") if "-" in dest else (dest, dest)
    return create_query(
        flights=[
            FlightQuery(date=dep.isoformat(), from_airport=o, to_airport=out_to),
            FlightQuery(date=ret.isoformat(), from_airport=back_from, to_airport=o),
        ],
        trip="round-trip" if out_to == back_from else "multi-city",
        seat="economy",
        passengers=Passengers(adults=CONFIG["adults"]),
        language="tr",
        currency=CONFIG["currency"],
        max_stops=max_stops,
        # safe: 1 bavul ücreti dahil, ayrı biletli / kendi aktarmalı uçuşlar hariç
        checked_bags=1 if safe else 0,
        hide_separate_and_self_transfer=safe,
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


def fetch(dest, dep, ret, max_stops, safe=False, attempts=3):
    q = build_query(dest, dep, ret, max_stops, safe)
    err = None
    for i in range(attempts):
        try:
            options = parse(fetch_flights_html(q))
            # Google ara sıra boş sonuç döndürüyor; birkaç kez daha dene.
            if options or i == attempts - 1:
                return options, q.url()
        except Exception as e:  # ağ hatası, engelleme, değişen sayfa yapısı
            err = e
        time.sleep(5 * (i + 1) + random.random() * 3)
    raise err


def summarize(direct_opts, conn_opts):
    direct = next((o for o in direct_opts if len(o["legs"]) == 1), None)
    conn = [o for o in conn_opts if len(o["legs"]) == 2 and short_enough(o)]
    return direct, conn[:3]


def short_enough(o):
    """Gidiş yolculuk süresi (aktarma beklemesi dahil) sınırın altında mı? Süre bilinmiyorsa eler."""
    limit = CONFIG.get("max_connecting_hours")
    return not limit or (o.get("minutes") is not None and o["minutes"] < limit * 60)


def load_data():
    if not DATA_FILE.exists():
        return {"runs": [], "combos": {}}
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    # Eski kayıtlar sadece Haneda içindi ve anahtarlarında havalimanı yoktu: "HND_" önekiyle taşı.
    migrated = {}
    for key, c in data["combos"].items():
        if "dest" not in c:
            c["dest"] = "HND"
            key = f"HND_{key}"
        migrated[key] = c
    data["combos"] = migrated
    return data


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


DIRECT_LOW_STEP = 1000  # aktarmasız "yeni en düşük" alarmı için gereken en az düşüş (TL)
PANEL_URL = "https://burakkaratopan-droid.github.io/ucus-takip/"


def last_value(entry, col):
    for p in reversed(entry["history"]):
        if len(p) > col and p[col] is not None:
            return p[col]
    return None


def tl(n):
    return f"{n:,}".replace(",", ".") + " TL"


def notify(alerts):
    """Alarm varsa GitHub'da bir issue açar; GitHub bunu depo sahibine e-postayla bildirir."""
    if not alerts:
        return
    title = "Fiyat alarmı: " + alerts[0]["title"] + (f" (+{len(alerts) - 1})" if len(alerts) > 1 else "")
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER")
    # Sahibi etiketleyip issue'yu ona atıyoruz: GitHub bu iki durumda izleme ayarından
    # bağımsız olarak e-posta gönderir.
    mention = f"@{owner} " if owner else ""
    body = (f"{mention}yeni fiyat alarmı:\n\n" + "\n".join(f"- {a['text']}" for a in alerts)
            + f"\n\n[Paneli aç]({PANEL_URL})")
    if not (token and repo):
        print("ALARM (GitHub dışında, issue açılmadı):\n" + title + "\n" + body)
        return
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues",
        data=json.dumps({"title": title, "body": body, "assignees": [owner] if owner else []}).encode(),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print("Alarm issue açıldı:", json.load(r).get("html_url"))
    except Exception as e:  # bildirim hatası taramayı bozmasın
        print("Alarm issue açılamadı:", e, file=sys.stderr)


def main():
    data = load_data()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["runs"].append(now)
    run_idx = len(data["runs"]) - 1
    combos = list(combinations())
    threshold = CONFIG["connecting_threshold"]
    ok = failed = 0

    # Alarm karşılaştırması için tarama öncesi durum
    prev_direct_low = min((p[1] for c in data["combos"].values() for p in c["history"] if p[1] is not None),
                          default=None)

    for n, (dest, hid, dep, ret, days) in enumerate(combos, 1):
        key = f"{dest}_{dep.isoformat()}_{ret.isoformat()}"
        try:
            direct_opts, direct_url = fetch(dest, dep, ret, 0)
            time.sleep(1 + random.random() * 2)
            conn_opts, conn_url = fetch(dest, dep, ret, 1)
            time.sleep(1 + random.random() * 2)
        except Exception as e:
            failed += 1
            print(f"[{n}/{len(combos)}] {key} HATA: {e}", file=sys.stderr)
            continue

        direct, conn = summarize(direct_opts, conn_opts)
        entry = data["combos"].setdefault(key, {
            "dest": dest, "holiday": hid, "dep": dep.isoformat(), "ret": ret.isoformat(),
            "days": days, "history": [],
        })
        # Google bazen boş döndürüyor: o zaman son bilinen fiyatı koru, "eski" diye işaretle.
        stale = {}
        if direct:
            entry["direct"] = compact_option(direct)
        elif entry.get("direct"):
            stale["direct"] = True
        if conn:
            entry["connecting"] = [compact_option(c) for c in conn]
        elif entry.get("connecting"):
            stale["connecting"] = True
        entry["stale"] = stale

        point = [run_idx,
                 entry["direct"]["price"] if entry.get("direct") else None,
                 entry["connecting"][0]["price"] if entry.get("connecting") else None]
        # Sadece fiyat değiştiğinde yeni nokta ekle; dosya küçük kalsın.
        if not entry["history"] or entry["history"][-1][1:3] != point[1:]:
            entry["history"].append(point)
        entry["checked"] = run_idx
        entry["urls"] = {"direct": direct_url, "connecting": conn_url}
        ok += 1
        print(f"[{n}/{len(combos)}] {key} aktarmasız={point[1]} aktarmalı={point[2]}"
              + (f" (eski: {', '.join(stale)})" if stale else ""))

    # Alarmlar
    alerts = []
    for key, entry in data["combos"].items():
        if entry.get("checked") != run_idx or entry["stale"].get("connecting") or not entry.get("connecting"):
            continue
        price, alerted = entry["connecting"][0]["price"], entry.get("alerted_conn")
        # Aynı kombinasyon için ancak daha önce bildirilenden daha ucuzsa tekrar haber ver.
        if price <= threshold and (alerted is None or price < alerted):
            entry["alerted_conn"] = price
            o = entry["connecting"][0]
            alerts.append({
                "title": f"{tl(price)} aktarmalı ({entry['dest']})",
                "text": f"IST ⇄ {entry['dest']} {entry['dep']} → {entry['ret']} ({entry['days']} gün): {tl(price)}, "
                        f"{', '.join(o['airlines'])} · {', '.join(o['via'])} aktarmalı."
                        f" [Google Flights]({entry['urls']['connecting']})",
            })
    lows = [(c["direct"]["price"], c) for c in data["combos"].values()
            if c.get("checked") == run_idx and c.get("direct") and not c["stale"].get("direct")]
    if lows and prev_direct_low is not None:
        price, c = min(lows, key=lambda x: x[0])
        if price <= prev_direct_low - DIRECT_LOW_STEP:
            alerts.append({
                "title": f"aktarmasız yeni en düşük {tl(price)} ({c['dest']})",
                "text": f"Aktarmasız şimdiye kadarki en düşük fiyat: IST ⇄ {c['dest']} {c['dep']} → {c['ret']} ({c['days']} gün) "
                        f"{tl(price)}, {', '.join(c['direct']['airlines'])} (önceki en düşük {tl(prev_direct_low)}). "
                        f"[Google Flights]({c['urls']['direct']})",
            })
    notify(alerts)

    data["updated"] = now
    data["config"] = CONFIG
    data["last_run"] = {
        "at": now, "ok": ok, "failed": failed, "total": len(combos),
        "stale": sum(1 for c in data["combos"].values() if c.get("checked") == run_idx and c["stale"]),
    }
    DATA_FILE.parent.mkdir(exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Bitti: {ok} başarılı, {failed} hatalı / {len(combos)}, {len(alerts)} alarm")
    # Hepsi başarısızsa iş akışı kırmızı görünsün.
    sys.exit(1 if ok == 0 and combos else 0)


if __name__ == "__main__":
    if "--test-alarm" in sys.argv:
        notify([{"title": "test", "text": "Bu bir test alarmıdır. Bu e-postayı aldıysan bildirimler çalışıyor."}])
    else:
        main()
