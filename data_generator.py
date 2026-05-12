import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from database import engine  # Kendi engine bağlantını import et

def generate_and_insert_bulk_data(days=1):
    # Başlangıç tarihi: Bugünün başı
    start_date = datetime(2026, 5, 13, 0, 0) 
    meter_ids = [f"MTR_{i:05d}" for i in range(1, 1001)] # MTR_00001 - MTR_01000
    
    all_records = []
    
    print(f"{len(meter_ids)} sayaç için {days} günlük veri üretiliyor...")

    for meter_id in meter_ids:
        for i in range(24 * days):
            current_time = start_date + timedelta(hours=i)
            hour = current_time.hour
            current_date = current_time.date()
            hour_str = f"{hour:02d}:00"
            
            # Tüketim mantığı (Fiziksel karakteristik)
            base_consumption = 30 + 15 * np.sin(2 * np.pi * (hour - 6) / 24)
            consumption = round(max(0.1, base_consumption + np.random.normal(0, 3)), 3)
            
            all_records.append({
                "date": current_date,
                "hour": hour_str,
                "meter_id": meter_id,
                "value": consumption,
                "data_typeid": 2  # Gerçek okuma tipi
            })

    # Veritabanına Toplu Yazma (Bulk Insert)
    df = pd.DataFrame(all_records)
    
    print(f"Toplam {len(df)} satır veritabanına yazılıyor...")
    
    try:
        # Hızlı insert için "multi" methodu kullanılır
        df.to_sql('meter_readings', con=engine, if_exists='append', index=False, method='multi', chunksize=5000)
        print("İşlem başarıyla tamamlandı!")
    except Exception as e:
        print(f"Hata oluştu: {e}")

def delete_meter_data_by_date(target_date_str):
    """
    Belirli bir tarihteki tüm sayaç verilerini siler.
    Örn: delete_meter_data_by_date("2026-05-12")
    """
    query = text("DELETE FROM meter_readings WHERE date = :target_date")
    
    try:
        with engine.connect() as conn:
            result = conn.execute(query, {"target_date": target_date_str})
            conn.commit()
            print(f"{target_date_str} tarihli {result.rowcount} adet kayıt silindi.")
    except Exception as e:
        print(f"Silme işlemi sırasında hata oluştu: {e}")

if __name__ == "__main__":
    # Önce temizle (varsa eski verileri siler, böylece mükerrer kayıt olmaz)
    # delete_meter_data_by_date("2026-05-12")
    # Sonra yeni verileri bas
    generate_and_insert_bulk_data(days=1)