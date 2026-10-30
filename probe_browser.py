"""Teşhis: açık çene sorgularını tarayıcıyla çalıştırıp ayrıştırılan sonuçları yazdırır."""
import time
from datetime import date
from pathlib import Path

import tracker

out = Path(__file__).parent / "probe"
out.mkdir(exist_ok=True)
dep, ret = date(2027, 3, 5), date(2027, 3, 17)
for dest in ["HND-NRT", "HND-KIX", "NRT-KIX", "HND-NRT"]:
    t = time.time()
    try:
        opts, url = tracker.fetch_browser(dest, dep, ret)
    except Exception as e:
        opts, url = [], f"HATA {e}"
    secs = time.time() - t
    tracker._page().screenshot(path=str(out / f"{dest}.png"))
    direct, conn = tracker.summarize(opts, opts)
    lines = [f"{dest} {secs:.1f} sn, {len(opts)} seçenek, {url}",
             f"  aktarmasız: {direct and (direct['price'], direct['airlines'], direct['minutes'])}"]
    lines += [f"  aktarmalı: {c['price']} {c['airlines']} {[l['to'] for l in c['legs'][:-1]]} {c['minutes']} dk" for c in conn]
    lines += [f"  ham: {o['price']} {o['airlines']} {len(o['legs'])-1} aktarma {o['minutes']} dk" for o in opts]
    (out / f"{dest}.raw.txt").write_text("\n=====\n".join(tracker._BROWSER.get("texts", [])), encoding="utf-8")
    (out / f"{dest}.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:6]))
tracker.close_browser()
