"""Teşhis: çoklu şehir sonuçlarını gerçek tarayıcıyla açıp sayfada fiyat görünüyor mu bakar."""
import sys
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

import tracker

out = Path(__file__).parent / "probe"
out.mkdir(exist_ok=True)
dep, ret = date(2027, 3, 5), date(2027, 3, 17)
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(locale="tr-TR", viewport={"width": 1280, "height": 2000})
    for dest, stops in [("HND-NRT", 1), ("HND-NRT", 0), ("NRT", 1)]:
        url = tracker.build_query(dest, dep, ret, stops).url()
        page.goto(url, wait_until="domcontentloaded")
        # Çerez onayı çıkarsa kabul et
        for label in ["Tümünü kabul et", "Accept all"]:
            btn = page.get_by_role("button", name=label)
            if btn.count():
                btn.first.click()
                page.wait_for_load_state("domcontentloaded")
                break
        try:
            page.wait_for_selector("li .YMlIz, li [aria-label*='TL']", timeout=30000)
        except Exception as e:
            print(dest, stops, "bekleme zaman aşımı", e)
        page.wait_for_timeout(3000)
        name = f"browser_{dest}_{stops}"
        page.screenshot(path=str(out / f"{name}.png"), full_page=False)
        items = page.locator("li").all_inner_texts()
        items = [i.replace("\n", " | ") for i in items if "TL" in i]
        (out / f"{name}.txt").write_text(url + "\n" + "\n".join(items), encoding="utf-8")
        print(dest, stops, "fiyatlı satır:", len(items))
        for i in items[:3]:
            print("  ", i[:200])
    b.close()
