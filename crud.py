from sqlalchemy.orm import Session
from datetime import date, datetime, timedelta
import models 
import pandas as pd
from models import VPPForecast

# --- METER READING FONKSİYONLARI (PLAN B / DASHBOARD) ---

def get_readings(db: Session, limit: int = None, days: int = None):
    """Genel veri çekme fonksiyonu (Dashboard ve Analiz için)"""
    query = db.query(models.MeterReading).order_by(models.MeterReading.timestamp.desc())
    
    if days:
        start_date = datetime.now() - timedelta(days=days)
        query = query.filter(models.MeterReading.timestamp >= start_date)
    
    if limit:
        query = query.limit(limit)
    
    return query.all()

def get_vpp_forecast_by_date(db: Session, target_date: date):
    """Plan A grafiği için verileri SAAT SIRALI ve organize döner."""
    # .order_by ekledik çünkü grafik 05:00 -> 01:00 diye atlarsa çizgi bozulur
    results = db.query(VPPForecast).filter(
        VPPForecast.date == target_date
    ).order_by(VPPForecast.hour).all() 
    
    # Frontend dostu format
    formatted_data = {
        "ptf": [r.value for r in results if r.datatype_id == 1],
        "load": [r.value for r in results if r.datatype_id == 2],
        "hours": sorted(list(set([r.hour for r in results]))) # Benzersiz ve sıralı saatler
    }
    return formatted_data

def get_24h_data_by_type(db: Session, target_date: date, datatype_id: int, model):
    """
    Belirli bir tablo (model) ve veri tipi (datatype_id) için 24 saatlik veriyi çeker.
    model: MarketData veya VPPForecast tablosu
    datatype_id: 1 (PTF), 2 (LOAD), 3 (SMF)
    """
    try:
        results =  db.query(model).filter(
            model.date == target_date,
            model.datatype_id == datatype_id
        ).order_by(model.date, model.hour).all()
        # Eğer veri 24 saatten eksikse veya hiç yoksa log basabilirsin
        if len(results) < 24:
            print(f"UYARI: {target_date} tarihi için sadece {len(results)} saatlik PTF verisi bulundu.")
        return results
    except Exception as e:
        print(f"HATA: get_24h_ptf_data çalışırken hata oluştu: {e}")
        return []

def insert_meter_reading(db: Session, timestamp, meter_id, consumption, price, smf=None, yal=None, yat=None):
    """Yeni IoT veya Piyasa verisi kaydetme fonksiyonu"""
    db_reading = models.MeterReading(
        timestamp=timestamp,
        meter_id=meter_id,
        consumption=consumption,
        price=price,
        smf=smf,
        yal=yal,
        yat=yat
    )
    db.add(db_reading)
    db.commit()
    db.refresh(db_reading)
    return db_reading

def insert_only_vpp_forecast(db: Session, target_date: date, hour: str, datatype_id: int, value: float):
    """Tekli tahmin verisi kaydetme veya güncelleme"""
    # Mevcut veri varsa sil (UniqueConstraint ihlalini önlemek için)
    db.query(VPPForecast).filter(
        VPPForecast.date == target_date,
        VPPForecast.hour == hour,
        VPPForecast.datatype_id == datatype_id
    ).delete()

    db_forecast = VPPForecast(
        date=target_date,
        hour=hour,
        datatype_id=datatype_id,
        value=value
    )
    db.add(db_forecast)
    db.commit()
    db.refresh(db_forecast)
    return db_forecast


# --- ESKİ FONKSİYONLARIN YENİ YAPIYA ADAPTASYONU ---

def insert_combined_vpp_forecasts(db: Session, ptf_list: list, load_list: list, target_date: date):
    """
    Hem PTF hem LOAD verilerini yeni tablo yapısına göre kaydeder.
    ptf_list: [{'hour': '00:00', 'price': 2500}, ...]
    load_list: [10.5, 11.2, ...] (24 adet float)
    """
    try:
        # Önce o tarihe ait eski PTF(1) ve LOAD(2) verilerini temizle
        db.query(VPPForecast).filter(
            VPPForecast.date == target_date,
            VPPForecast.datatype_id.in_([1, 2])
        ).delete()

        new_records = []
        for i in range(24):
            hour_str = f"{i:02d}:00"
            
            # PTF Kaydı (ID: 1)
            ptf_val = ptf_list[i].get('price', 0.0) if i < len(ptf_list) else 0.0
            new_records.append(VPPForecast(date=target_date, hour=hour_str, datatype_id=1, value=ptf_val))
            
            # LOAD Kaydı (ID: 2)
            load_val = load_list[i] if i < len(load_list) else 0.0
            new_records.append(VPPForecast(date=target_date, hour=hour_str, datatype_id=2, value=load_val))

        db.add_all(new_records)
        db.commit()
        print(f"BAŞARILI: {target_date} için PTF ve LOAD verileri kaydedildi.")
    except Exception as e:
        db.rollback()
        print(f"HATA: Kayıt sırasında sorun oluştu: {e}")

# --- VPP FORECAST FONKSİYONLARI (PLAN A / STRATEJİK) ---
def bulk_insert_vpp_forecasts(db: Session, df: pd.DataFrame, datatype_id: int):
    try:
        # 1. Tarih Formatı: EPİAŞ'tan gelen 'date' sütununu Python 'date' objesine çevir
        if not pd.api.types.is_datetime64_any_dtype(df['date']):
            df['date'] = pd.to_datetime(df['date']).dt.date

        target_dates = df['date'].unique()

        # 2. Temizlik: Mevcut kayıtları sil (Overwrite mantığı)
        db.query(VPPForecast).filter(
            VPPForecast.date.in_(target_dates),
            VPPForecast.datatype_id == datatype_id
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
                datatype_id=datatype_id,
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

from models import MarketData

def bulk_insert_market_data(db: Session, df: pd.DataFrame, datatype_id: int = None):
    """
    Pandas DataFrame verisini market_data tablosuna toplu olarak ekler.
    data_name: 'PTF', 'SMF', 'YAL', 'YAT' gibi...
    """
    try:
        # Önce mükerrer kayıt hatası almamak için o tarihteki aynı isimli verileri temizleyebilirsin
        target_dates = df['date'].unique()
        db.query(MarketData).filter(
            MarketData.date.in_(target_dates),
            MarketData.datatype_id == datatype_id
        ).delete(synchronize_session=False)

        records = [
            MarketData(
                date=row['date'],
                hour=row['hour'],
                datatype_id=datatype_id,
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




def delete_forecasts_by_date(db: Session, target_date: date, datatype_id: int = None):
    """Belirli bir tarihteki verileri temizler"""
    query = db.query(VPPForecast).filter(VPPForecast.date == target_date)
    if datatype_id:
        query = query.filter(VPPForecast.datatype_id == datatype_id)
    query.delete()
    db.commit()
