# İstanbul ⇄ Tokyo bayram uçuş takipçisi

IST ⇄ HND gidiş-dönüş fiyatlarını günde üç kez (TR saatiyle 08:00, 14:00, 20:00) Google Flights'tan çeker.

- Ramazan ve Kurban bayramlarını **arife dahil tamamen** kapsayan 10–15 günlük tüm kombinasyonlar (2027 için 120 adet)
- Aktarmasız en ucuz fiyat ve en ucuz 3 tek aktarmalı seçenek
- 40.000 TL altındaki tek aktarmalılar panelde işaretlenir
- Fiyatlar tek yetişkin, ekonomi, gidiş-dönüş toplam, TL

## Dosyalar

| Dosya | Ne işe yarar |
|---|---|
| `config.json` | Rota, bayram tarihleri, gün aralığı, 40 bin TL eşiği |
| `tracker.py` | Taramayı yapar, sonuçları `docs/data.json`'a ekler |
| `docs/index.html` | Panel (GitHub Pages) |
| `.github/workflows/track.yml` | Günde 3 kez otomatik çalıştırır |

## Ayar değiştirmek

`config.json` dosyasını GitHub üzerinde düzenleyip kaydetmen yeterli; bir sonraki taramada geçerli olur.
2028 bayramlarını eklemek için `holidays` listesine yeni satır ekle.

## Elle tarama başlatmak

GitHub'da **Actions → Fiyat taraması → Run workflow**.

## Yerelde çalıştırmak

```bash
pip install -r requirements.txt
python tracker.py
```
