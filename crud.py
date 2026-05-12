from sqlalchemy.orm import Session
from datetime import date, datetime, timedelta
import pandas as pd
from models import MeterReading, MarketData, VPPForecast
from database import SessionLocal

# --- METER READING FONKSİYONLARI (PLAN B / DASHBOARD) ---
def get_readings(db: Session, meter_id: str = None, limit: int = None, days: int = None):
    """Genel veri çekme fonksiyonu - Sütun isimleri modele göre düzeltildi"""
    query = db.query(MeterReading)
    
    # Meter_id filtresi eklendi
    if meter_id:
        query = query.filter(MeterReading.meter_id == meter_id)
        
    if days:
        start_date = datetime.now() - timedelta(days=days)
        query = query.filter(MeterReading.date >= start_date)
    
    # Timestamp yerine date ve hour kullanıyoruz
    query = query.order_by(MeterReading.date.desc(), MeterReading.hour.desc())
    
    if limit:
        query = query.limit(limit)
    
    # Tek bir nesne lazımsa .first() kullanılır, liste lazımsa .all()
    return query.first() if limit == 1 else query.all()


def get_vpp_forecast_by_date(db: Session, target_date: date):
    """Plan A grafiği için verileri SAAT SIRALI ve organize döner."""
    # .order_by ekledik çünkü grafik 05:00 -> 01:00 diye atlarsa çizgi bozulur
    results = db.query(VPPForecast).filter(
        VPPForecast.date == target_date
    ).order_by(VPPForecast.hour).all() 
    
    # Frontend dostu format
    formatted_data = {
        "ptf": [r.value for r in results if r.data_typeid == 1],
        "load": [r.value for r in results if r.data_typeid == 2],
        "hours": sorted(list(set([r.hour for r in results]))) # Benzersiz ve sıralı saatler
    }
    return formatted_data

def get_24h_data_by_type(db: Session, target_date: date, data_typeid: int, model):
    """
    Belirli bir tablo (model) ve veri tipi (data_typeid) için 24 saatlik veriyi çeker.
    model: MarketData veya VPPForecast tablosu
    data_typeid: 1 (PTF), 2 (LOAD), 3 (SMF)
    """
    try:
        results =  db.query(model).filter(
            model.date == target_date,
            model.data_typeid == data_typeid
        ).order_by(model.date, model.hour).all()
        # Eğer veri 24 saatten eksikse veya hiç yoksa log basabilirsin
        if len(results) < 24:
            print(f"UYARI: {target_date} tarihi için sadece {len(results)} saatlik PTF verisi bulundu.")
        
        return results
    except Exception as e:
        print(f"HATA: get_24h_ptf_data çalışırken hata oluştu: {e}")
        return []
"""
def insert_meter_reading(db: Session, date, hour, meter_id, value):
    "Yeni IoT veya Piyasa verisi kaydetme fonksiyonu"
    db_reading = MeterReading(
        date=date,
        hour=hour,
        meter_id=meter_id,
        value=value
    )
    db.add(db_reading)
    db.commit()
    db.refresh(db_reading)
    return db_reading

def insert_only_vpp_forecast(db: Session, target_date: date, hour: str, data_typeid: int, value: float):
    "Tekli tahmin verisi kaydetme veya güncelleme"
    # Mevcut veri varsa sil (UniqueConstraint ihlalini önlemek için)
    db.query(VPPForecast).filter(
        VPPForecast.date == target_date,
        VPPForecast.hour == hour,
        VPPForecast.data_typeid == data_typeid
    ).delete()

    db_forecast = VPPForecast(
        date=target_date,
        hour=hour,
        data_typeid=data_typeid,
        value=value
    )
    db.add(db_forecast)
    db.commit()
    db.refresh(db_forecast)
    return db_forecast


# --- ESKİ FONKSİYONLARIN YENİ YAPIYA ADAPTASYONU ---

def insert_combined_vpp_forecasts(db: Session, ptf_list: list, load_list: list, target_date: date):
    "    Hem PTF hem LOAD verilerini yeni tablo yapısına göre kaydeder.    ptf_list: [{'hour': '00:00', 'price': 2500}, ...]    load_list: [10.5, 11.2, ...] (24 adet float)"
    try:
        # Önce o tarihe ait eski PTF(1) ve LOAD(2) verilerini temizle
        db.query(VPPForecast).filter(
            VPPForecast.date == target_date,
            VPPForecast.data_typeid.in_([1, 2])
        ).delete()

        new_records = []
        for i in range(24):
            hour_str = f"{i:02d}:00"
            
            # PTF Kaydı (ID: 1)
            ptf_val = ptf_list[i].get('price', 0.0) if i < len(ptf_list) else 0.0
            new_records.append(VPPForecast(date=target_date, hour=hour_str, data_typeid=1, value=ptf_val))
            
            # LOAD Kaydı (ID: 2)
            load_val = load_list[i] if i < len(load_list) else 0.0
            new_records.append(VPPForecast(date=target_date, hour=hour_str, data_typeid=2, value=load_val))

        db.add_all(new_records)
        db.commit()
        print(f"BAŞARILI: {target_date} için PTF ve LOAD verileri kaydedildi.")
    except Exception as e:
        db.rollback()
        print(f"HATA: Kayıt sırasında sorun oluştu: {e}")

# --- VPP FORECAST FONKSİYONLARI (PLAN A / STRATEJİK) ---
def bulk_insert_vpp_forecasts(db: Session, df: pd.DataFrame, data_typeid: int):
    try:
        # 1. Tarih Formatı: EPİAŞ'tan gelen 'date' sütununu Python 'date' objesine çevir
        if not pd.api.types.is_datetime64_any_dtype(df['date']):
            df['date'] = pd.to_datetime(df['date']).dt.date

        target_dates = df['date'].unique()

        # 2. Temizlik: Mevcut kayıtları sil (Overwrite mantığı)
        db.query(VPPForecast).filter(
            VPPForecast.date.in_(target_dates),
            VPPForecast.data_typeid == data_typeid
        ).delete(synchronize_session=False)

        # 3. Saat Formatı: EPİAŞ'tan bazen "0", "1" gibi rakam gelebilir.
        # Bunu "00:00", "01:00" formatına (String(5)) zorlayalım.
        def format_hour(h):
            h_str = str(h).split(':')[0] # Eğer 14:00:00 gelirse 14'ü al
            return f"{int(h_str):02d}:00"

        records = [
            VPPForecast(
                date=row['date'],
                hour=format_hour(row['hour']), 
                data_typeid=data_typeid,
                value=float(row['value'])
            )
            for _, row in df.iterrows()
        ]

        db.bulk_save_objects(records)
        db.commit()
        return len(records)
    except Exception as e:
        db.rollback()
        print(f"HATA: {e}")
        raise e

def bulk_insert_market_data(db: Session, df: pd.DataFrame, data_typeid: int = None):
    "Pandas DataFrame verisini market_data tablosuna toplu olarak ekler.    data_name: 'PTF', 'SMF', 'YAL', 'YAT' gibi...    "
    try:
        # Önce mükerrer kayıt hatası almamak için o tarihteki aynı isimli verileri temizleyebilirsin
        target_dates = df['date'].unique()
        db.query(MarketData).filter(
            MarketData.date.in_(target_dates),
            MarketData.data_typeid == data_typeid
        ).delete(synchronize_session=False)

        records = [
            MarketData(
                date=row['date'],
                hour=row['hour'],
                data_typeid=data_typeid,
                value=row['value']
            )
            for _, row in df.iterrows()
        ]
        db.bulk_save_objects(records)
        db.commit()
        return len(records)
    except Exception as e:
        db.rollback()
        print(f"Market Data Insert Hatası: {e}")
        raise e

def delete_forecasts_by_date(db: Session, target_date: date, data_typeid: int = None):
    "Belirli bir tarihteki verileri temizler"
    query = db.query(VPPForecast).filter(VPPForecast.date == target_date)
    if data_typeid:
        query = query.filter(VPPForecast.data_typeid == data_typeid)
    query.delete()
    db.commit()

"""