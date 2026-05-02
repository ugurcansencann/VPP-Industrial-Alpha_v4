from sqlalchemy.orm import Session
from datetime import date, datetime, timedelta
import models 
import requests
import pandas as pd
from sqlalchemy.orm import Session
from models import VPPForecast # Model ismine göre güncelle

def get_readings(db: Session, limit: int = None, days: int = None):
    """Genel veri çekme fonksiyonu (Dashboard ve Analiz için)"""
    query = db.query(models.MeterReading).order_by(models.MeterReading.timestamp.desc())
    
    if days:
        start_date = datetime.now() - timedelta(days=days)
        query = query.filter(models.MeterReading.timestamp >= start_date)
    
    if limit:
        query = query.limit(limit)
    
    return query.all()

def create_meter_reading(db: Session, timestamp, meter_id, consumption, price, smf=None, yal=None, yat=None):
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

def get_recent_readings(db: Session, limit: int = 10):
    """Dashboard'daki tablo için en güncel verileri getirir"""
    return db.query(models.MeterReading).order_by(models.MeterReading.timestamp.desc()).limit(limit).all()

def get_last_24h_prices(db: Session):
    """DB'deki son 24 saatlik PTF (price) değerlerini getirir."""
    one_day_ago = datetime.now() - timedelta(days=1)
    return db.query(models.MeterReading)\
        .filter(models.MeterReading.timestamp >= one_day_ago)\
        .order_by(models.MeterReading.timestamp.asc())\
        .all()

def save_ml_forecast(db: Session, timestamp: datetime, predicted_val: float, expected_price: float):
    """ML modelinden gelen tahmin çıktılarını DB'ye yazar."""
    db_forecast = models.VPPForecast(
        timestamp=timestamp,
        predicted_consumption=predicted_val,
        expected_price=expected_price
    )
    db.add(db_forecast)
    db.commit()
    db.refresh(db_forecast)
    return db_forecast

def get_tomorrow_forecasts(db: Session):
    """DB'den yarın için kaydedilmiş tahmin çıktılarını çeker."""
    tomorrow = datetime.now().date() + timedelta(days=1)
    return db.query(models.VPPForecast)\
        .filter(models.VPPForecast.date >= datetime.combine(tomorrow, datetime.min.time()))\
        .order_by(models.VPPForecast.date.asc())\
        .all()


def get_tomorrow_ptf():
    """
    EPİAŞ Şeffaflık Platformu üzerinden yarınki PTF verilerini çeker.
    """
    # Yarınki tarihi belirle
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    
    # EPİAŞ Şeffaflık Platformu Üretim/Fiyat API URL (Örnek mimari)
    url = "https://seffaflik.epias.com.tr/transparency/service/market/day-ahead-mcp"
    
    params = {
        "startDate": tomorrow,
        "endDate": tomorrow,
        "displayLanguage": "tr"
    }

    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            # Veriyi işle ve DataFrame'e çevir
            df = pd.DataFrame(data['body']['dayAheadMCPList'])
            # Sadece saat ve fiyat kolonlarını alalım
            df = df[['date', 'price']]
            print(f"{tomorrow} tarihi için {len(df)} saatlik veri başarıyla çekildi.")
            return df
        else:
            print(f"Hata: EPİAŞ servisi {response.status_code} koduyla yanıt verdi.")
            return None
    except Exception as e:
        print(f"Bağlantı hatası: {e}")
        return None
    


def save_tomorrow_forecasts(db: Session, ptf_data: list, load_forecasts: list):
    """
    EPİAŞ fiyatlarını ve ML yük tahminlerini DB'ye kaydeder.
    """
    for i in range(24):
        new_entry = VPPForecast(
            hour=i,
            expected_price=ptf_data[i]['price'],
            predicted_consumption=load_forecasts[i],
            date=(datetime.now() + timedelta(days=1)).date()
        )
        db.add(new_entry)
    db.commit()
# Test etmek için:
# if __name__ == "__main__":
#     print(get_tomorrow_ptf())


def save_vpp_forecast(db: Session, ptf_data: list, predicted_loads: list):
    tomorrow = (datetime.now() + timedelta(days=1)).date()
    
    # 1. Mevcut veriyi temizle
    db.query(models.VPPForecast).filter(models.VPPForecast.date == tomorrow).delete()
    
    # 2. Veri kontrolü ekle
    if not ptf_data or len(ptf_data) == 0:
        print("UYARI: EPİAŞ'tan fiyat verisi alınamadı, işlem iptal edildi.")
        return

    for i in range(24):
        hour_str = f"{i:02d}:00"
        
        # 'price' anahtarının varlığını kontrol et
        try:
            current_price = ptf_data[i].get('price', 0.0) if i < len(ptf_data) else 0.0
        except AttributeError:
            current_price = 0.0 # Eğer ptf_data bir dict listesi değilse
        
        db_forecast = models.VPPForecast(
            date=tomorrow,
            hour=hour_str,
            expected_price=current_price,
            predicted_load=predicted_loads[i] if i < len(predicted_loads) else 0.0
        )
        db.add(db_forecast)
    
    try:
        db.commit()
        print(f"BAŞARILI: {tomorrow} tarihi için 24 saatlik veri kaydedildi.")
    except Exception as e:
        db.rollback()
        print(f"HATA: Veritabanı kaydı başarısız: {e}")

        
def get_vpp_forecast_by_date(db: Session, target_date: date):
    """Belirli bir tarihteki tüm tahmin verilerini getirir."""
    return db.query(models.VPPForecast).filter(models.VPPForecast.date == target_date).all()