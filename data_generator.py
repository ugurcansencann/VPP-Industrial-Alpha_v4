import pandas as pd
import numpy as np
import sys
from datetime import datetime, timedelta
from sqlalchemy import text
from database_setup import engine 

def generate_meter_data(meter_ids, target_time):
    """Belirli bir zaman dilimi için tüm sayaçlara veri üretir."""
    hour = target_time.hour
    current_date_str = target_time.strftime("%Y-%m-%d")
    hour_str = f"{hour:02d}:00"

    records = []
    for meter_id in meter_ids:
        # Tüketim mantığı (Mevsimsel sinüs dalgası + gürültü)
        base_consumption = 30 + 15 * np.sin(2 * np.pi * (hour - 6) / 24)
        consumption = round(max(0.1, base_consumption + np.random.normal(0, 3)), 3)
        
        records.append({
            "date": current_date_str,
            "hour": hour_str,
            "data_typeid": 2,
            "meter_id": meter_id,
            "value": consumption            
        })
    return records

def run_generator(mode="daily", h_count=1):
    meter_ids = [f"MTR_{i:05d}" for i in range(1, 1001)]
    all_records = []
    
    # Şu anki saati al ve dakikaları sıfırla (örn 15:45 -> 15:00)
    now = datetime.now().replace(minute=0, second=0, microsecond=0)

    if mode == "hourly":
        # Belirtilen saat sayısı kadar geriye git ve her saat için veri üret
        print(f"Saatlik mod aktif: Son {h_count} saat için veriler üretiliyor...")
        for i in range(h_count, 0, -1):
            # i=1 ise son 1 saati, i=5 ise 5 saat öncesinden başlayarak üretir
            target_time = now - timedelta(hours=i)
            print(f"-> {target_time.strftime('%Y-%m-%d %H:00')} işleniyor...")
            all_records.extend(generate_meter_data(meter_ids, target_time))
        
    else:
        # GÜNLÜK MOD: Belirli bir tarihten başla (Varsayılan 24 saat)
        start_date = datetime(2026, 5, 13, 0, 0)
        print(f"Günlük mod aktif: {start_date.date()} için 24 saatlik veri üretiliyor...")
        for h in range(24):
            target_time = start_date + timedelta(hours=h)
            all_records.extend(generate_meter_data(meter_ids, target_time))

    # Veritabanına Yazma
    if all_records:
        df = pd.DataFrame(all_records)
        try:
            df.to_sql('meter_readings', con=engine, if_exists='append', index=False, method='multi', chunksize=5000)
            print(f"\nBaşarılı! Toplam {len(df)} satır veritabanına eklendi.")
        except Exception as e:
            print(f"Veritabanı hatası: {e}")

if __name__ == "__main__":
    # Kullanım: python data_generator.py hourly 5
    if len(sys.argv) > 1 and sys.argv[1] == "hourly":
        # Eğer sayı verilmezse varsayılan olarak 1 saat işlem yapar
        count = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        run_generator(mode="hourly", h_count=count)
    else:
        # Kullanım: python data_generator.py
        run_generator(mode="daily")

def delete_meter_data_by_date(target_date_str):
    query = text("DELETE FROM meter_readings WHERE date = :target_date")
    try:
        with engine.connect() as conn:
            result = conn.execute(query, {"target_date": target_date_str})
            conn.commit()
            print(f"{target_date_str} tarihli {result.rowcount} kayıt silindi.")
    except Exception as e:
        print(f"Silme hatası: {e}")



"""
1. Manuel / Toplu Veri Basma (Senin her zamanki yöntemin):
Bu komut 13 Mayıs için tüm günün (24.000 satır) verisini basar.

Bash
python data_generator.py

2. Saatlik IoT Simülasyonu (Yeni Özellik):
Bu komut çalıştığı andaki sistem saatini alır (örneğin saat 15:20 ise 15:00 kabul eder) ve 1000 sayaç için o saate ait veriyi (1000 satır) anında basar.

Bash
python data_generator.py hourly
"""