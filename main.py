from fastapi import FastAPI, Depends, HTTPException
import pandas as pd, joblib, redis, json, subprocess, os, random
from pulp import LpProblem, LpMinimize, LpVariable, value, PULP_CBC_CMD
from fastapi.responses import HTMLResponse
# Veritabanı bileşenleri
from sqlalchemy.orm import Session
import crud
from models import MeterReading, MarketData, VPPForecast, VPPMeterForecast, MLModelSimulation
from kpi_engine import calculate_vpp_performance
import numpy as np

# Modellerin hafızaya yüklenmesi için bu import şart
# Tabloları oluştur (Eğer tablolar silindiyse otomatik oluşturur)
from database_setup import SessionLocal, engine, Base, get_db # main'de tanımlama, buradan çek
import models 
Base.metadata.create_all(bind=engine)

app = FastAPI(title="VPP-Industrial-Alpha API")

# Redis bağlantısı
cache = redis.Redis(host='redis', port=6379, db=0)

# Modeli yükle (Dosya yoksa hata vermemesi için kontrol eklenebilir)
try:
    model = joblib.load("consumption_model.pkl")
except:
    model = None
    print("UYARI: consumption_model.pkl bulunamadı. Lütfen /retrain endpoint'ini kullanın.")

@app.get("/")
def home():
    return {"message": "VPP-Industrial-Alpha Akıllı Enerji Yönetim Sistemine Hoş Geldiniz!"}

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    try:
        with open("templates/index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Dashboard dosyası (templates/index.html) bulunamadı!</h1>"
from sqlalchemy.orm import Session
from sqlalchemy import and_
from forecast_opt_service import calculate_vpp_optimization, summarize_vpp_results
async def ensure_forecast_exists(db: Session, target_date, meter_id):
    """
    Bölüm 1: Eğer veritabanında o güne ait veri yoksa tahmin üretir.
    """
    existing_count = db.query(VPPMeterForecast).filter(
        VPPMeterForecast.date == target_date,
        VPPMeterForecast.meter_id == meter_id
    ).count()

    if existing_count >= 24:
        return # Veri zaten var, tahmine gerek yok.

    # Tahmin üretme mantığı buraya (Eski Bölüm 1)
    recent_readings = db.query(MeterReading).filter(MeterReading.meter_id == meter_id)\
        .order_by(MeterReading.date.desc(), MeterReading.hour.desc()).limit(24).all()

    if len(recent_readings) < 24:
        raise Exception("Tahmin için yeterli geçmiş veri yok.")

    day_of_week = target_date.weekday()
    lag_1h, lag_24h = recent_readings[0].value, recent_readings[23].value
    
    forecast_objects = []
    for h in range(24):
        input_df = pd.DataFrame([[h, day_of_week, lag_1h, lag_24h]], 
                                columns=['hour', 'day_of_week', 'lag_1', 'lag_24'])
        prediction = float(model.predict(input_df)[0])
        forecast_objects.append(VPPMeterForecast(
            date=target_date, hour=f"{h:02d}:00", 
            predicted_value=round(prediction, 3), meter_id=meter_id
        ))
    
    db.add_all(forecast_objects)
    db.commit()

@app.get("/api/v1/market-data/planA")
async def get_latest_market_data_planA(db: Session = Depends(get_db)):
    if model is None:
        raise HTTPException(status_code=500, detail="ML Modeli (.pkl) bulunamadı.")

    now = datetime.now()
    if now.hour >= 14:
        target_date = now.date() + timedelta(days=0)
    else:
        target_date = now.date()
    meter_id = "MTR_00001"

    try:
        # --- BÖLÜM 1: TAHMİN ÜRET VE KAYDET ---
        # --- ADIM 1: KONTROL VE TAHMİN (Sadece gerekiyorsa çalışır) ---
        await ensure_forecast_exists(db, target_date, meter_id)

        # --- BÖLÜM 2: VERİ BİRLEŞTİRME & SERVİS İLE OPTİMİZASYON ---
        results = db.query(
            VPPMeterForecast.hour,
            VPPMeterForecast.predicted_value.label("load"),
            MarketData.value.label("ptf")
        ).outerjoin(
            MarketData, 
            and_(
                MarketData.date == VPPMeterForecast.date,
                MarketData.hour == VPPMeterForecast.hour,
                MarketData.data_typeid == 1
            )
        ).filter(VPPMeterForecast.date == target_date, VPPMeterForecast.meter_id == meter_id)\
         .order_by(VPPMeterForecast.hour.asc()).all()

        dashboard_data = []
        for r in results:
            # Veritabanından PTF veya Load boş (None) gelmiş olabilir.
            # 'or 0.0' kullanarak None gelmesi durumunda 0.0 atanmasını garanti ediyoruz.
            ptf_val = float(r.ptf) if r.ptf is not None else 0.0
            load_val = float(r.load) if r.load is not None else 0.0
            
            # Servisi çağırırken artık None gitme ihtimali yok
            opt_results = calculate_vpp_optimization(load_val, ptf_val, smf=None)
            
            dashboard_data.append({
                "hour": r.hour,
                "ptf": ptf_val,
                **opt_results
            })

        # Özet verileri servis üzerinden toparla
        summary = summarize_vpp_results(dashboard_data)

        return {
            "status": "success",
            "metadata": {
                "target_date": target_date.isoformat(),
                **summary
            },
            "data": dashboard_data
        }

    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

from fastapi import FastAPI, Query
from datetime import datetime, timedelta
from crud import get_24h_data_by_type 
@app.get("/api/v1/market-data/planB")
async def get_latest_market_data_planB(db: Session = Depends(get_db)):
    now = datetime.now()
    
    # 1. Hedef Tarih Belirleme (14:00 Kuralı)
    # Eğer saat 14:00'ü geçtiyse hedef yarındır, geçmediyse bugündür.
    if now.hour >= 14:
        target_date = now.date() + timedelta(days=0)
    else:
        target_date = now.date()
    
    # 2. Verileri Çek
    ptf_results = crud.get_24h_data_by_type(db, target_date, 1, MarketData)
    load_results = crud.get_24h_data_by_type(db, target_date, 2, VPPForecast)
    smf_results = crud.get_24h_data_by_type(db, target_date, 3, MarketData)

    # 3. Fallback (Yarın verisi henüz manuel girilmemişse bugüne dön)
    if not ptf_results and target_date > now.date():
        target_date = now.date()
        ptf_results = crud.get_24h_data_by_type(db, target_date, 1, MarketData)
        load_results = crud.get_24h_data_by_type(db, target_date, 2, VPPForecast)
        smf_results = crud.get_24h_data_by_type(db, target_date, 3, MarketData)

    # 4. Veri Birleştirme (Frontend'in beklediği format)
    # 24 saatlik bir sözlük oluşturarak ptf ve load'u eşleştiriyoruz
    combined = {f"{i:02d}:00": {"hour": f"{i:02d}:00", "ptf": 0.0, "load": 0.0, "smf": 0.0} for i in range(24)}
    
    for r in ptf_results:
        combined[r.hour]["ptf"] = round(float(r.value), 2)
    
    for r in load_results:
        combined[r.hour]["load"] = round(float(r.value), 2)

    for r in smf_results:
        combined[r.hour]["smf"] = round(float(r.value), 2)

    return {
        "status": "success",
        "date": target_date.strftime('%Y-%m-%d'),
        "is_tomorrow": target_date > now.date(),
        "data": list(combined.values())
    }

@app.get("/api/v1/market-data/planF")
async def get_latest_market_data_planF(db: Session = Depends(get_db)):
    now = datetime.now()
    
    # 1. Hedef Tarih Belirleme (14:00 Kuralı)
    # Eğer saat 14:00'ü geçtiyse hedef yarındır, geçmediyse bugündür.
    if now.hour >= 14:
        target_date = now.date() + timedelta(days=0)
    else:
        target_date = now.date()
    
    # 2. Verileri Çek
    ptf_results = crud.get_24h_data_by_type(db, target_date, 1, MarketData)
    predicted_ptf_results = crud.get_24h_data_by_type(db, target_date, 1, VPPForecast)

    # 3. Fallback (Yarın verisi henüz manuel girilmemişse bugüne dön)
    if not ptf_results and target_date > now.date():
        target_date = now.date()
        ptf_results = crud.get_24h_data_by_type(db, target_date, 1, MarketData)
        predicted_ptf_results = crud.get_24h_data_by_type(db, target_date, 1, VPPForecast)

    # 4. Veri Birleştirme (Frontend'in beklediği format)
    # 24 saatlik bir sözlük oluşturarak ptf ve load'u eşleştiriyoruz
    combined = {f"{i:02d}:00": {"hour": f"{i:02d}:00", "ptf": 0.0, "forecasted_ptf": 0.0} for i in range(24)}
    
    for r in ptf_results:
        combined[r.hour]["ptf"] = round(float(r.value), 2)
    
    for r in predicted_ptf_results:
        combined[r.hour]["forecasted_ptf"] = round(float(r.value), 2)

    return {
        "status": "success",
        "date": target_date.strftime('%Y-%m-%d'),
        "is_tomorrow": target_date > now.date(),
        "data": list(combined.values())
    }


# --- 4. GEÇMİŞ VERİ VE DASHBOARD --- # --- REFRESH LOGIC ---
@app.get("/history")
def get_history(db: Session = Depends(get_db)):
    # CRUD metodu içindeki limit parametresini 24 olarak kullanıyoruz
    history = crud.get_readings(db, limit=24)
    
    # Dashboard grafiği soldan sağa (eskiden yeniye) aksın diye 
    # listeyi ters çevirip (Pythonic slice ile) gönderiyoruz.
    return history[::-1]

# --- 1. MODEL YENİDEN EĞİTİM (MLOps) ---
from fastapi import APIRouter, Depends
from train_model import run_ml_pipeline
from forecast_opt_service import generate_and_save_forecasts

@app.post("/vpp/retrain")
def retrain_model():
    """Dashboard'dan gelen 'Eğit' isteği. 
    Limitli veri (örn: son 168 saat) ile .pkl'yi tazeler."""
    result = run_ml_pipeline(mode="retrain", limit=168)
    return {"status": "Model Güncellendi", "metrics": result}

@app.post("/vpp/generate-forecast")
def trigger_forecast(db: Session = Depends(get_db)):
    """Plan A'ya basınca çalışacak kısım. 
    Mevcut .pkl'yi kullanır ve tahminleri DB'ye yazar."""
    count = generate_and_save_forecasts(db)
    return {"status": "Başarılı", "saved_forecast_count": count}

@app.get("/vpp/dashboard-data")
def get_dashboard_data(db: Session = Depends(get_db)):
    """Dashboard grafiklerine basılacak veriyi döndürür."""
    forecasts = db.query(VPPForecast).order_by(VPPForecast.date.desc()).limit(24).all()
    # Market verilerini de buraya ekleyebilirsin
    return {"forecasts": forecasts}

from train_model import train_and_log_model
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
import joblib
import pandas as pd

@app.post("/api/v1/retrain-and-refresh")
async def retrain_and_refresh(db: Session = Depends(get_db)):
    try:
        now = datetime.now()
        target_date = now.date()
        current_hour = now.hour
        meter_id = "MTR_00001"

        # 1. Eğitim Verisini Çek ve Model Eğit
        readings = db.query(MeterReading).filter(MeterReading.meter_id == meter_id).all()
        if not readings:
            raise Exception("Eğitim için veritabanında okuma bulunamadı.")
            
        path, params, metrics, features, count = train_and_log_model(readings)

        # Eğitim tarih aralığını belirle
        start_dt = min(r.date for r in readings)
        end_dt = max(r.date for r in readings)

        # 2. Rolling Forecast ve Finansal Hesaplama Hazırlığı
        active_model = joblib.load("consumption_model.pkl")
        latest_actual = db.query(MeterReading).filter(MeterReading.meter_id == meter_id)\
                          .order_by(MeterReading.date.desc(), MeterReading.hour.desc()).first()

        total_kwh_reduction = 0.0
        total_tl_savings = 0.0

        # Kalan saatler için revize tahminler
        for h in range(current_hour + 1, 24):
            input_df = pd.DataFrame([[h, target_date.weekday(), latest_actual.value, latest_actual.value]], 
                                    columns=['hour', 'day_of_week', 'lag_1', 'lag_24'])
            
            new_pred = float(active_model.predict(input_df)[0])
            
            # --- TASARRUF HESABI (Opsiyonel: Eğer fiyat tablon varsa oradan çekebilirsin) ---
            # Şimdilik örnek: Tahmin edilenin %10'u kadar bir optimizasyon öngörüldüğünü varsayalım
            # Veya sadece toplam tahmin edilen yükü toplayabilirsin.
            total_kwh_reduction += (new_pred * 0.15) # Örn: %15 yük kaydırma potansiyeli
            total_tl_savings += (new_pred * 0.15 * 2.5) # Örn: 2.5 TL birim fiyat üzerinden

            # DB Güncelleme
            db.query(VPPMeterForecast).filter(
                VPPMeterForecast.date == target_date,
                VPPMeterForecast.hour == f"{h:02d}:00",
                VPPMeterForecast.meter_id == meter_id
            ).update({"predicted_value": round(new_pred, 3)})

        # 3. Kapsamlı Log Oluşturma
        new_log = MLModelSimulation(
            run_date = datetime.now(),
            model_name=os.path.basename(path),
            model_path=path,
            rmse=metrics["rmse"],
            mae=metrics["mae"],
            r2_score=metrics["r2"],
            mape=metrics.get("mape"),
            sample_count=count,
            training_start_date=start_dt,
            training_end_date=end_dt,
            simulated_total_reduction=round(total_kwh_reduction, 2),
            simulated_total_savings=round(total_tl_savings, 2),
            hyperparameters=params,
            features_used=features,
            training_notes=f"Kullanıcı tetiklemeli rolling update. Saat: {current_hour}:00"
        )
        
        db.add(new_log)
        db.commit() # Tüm işlemler başarılıysa tek seferde commit
        
        return {
            "status": "success",
            "metrics": metrics,
            "simulation_id": new_log.id,
            "summary": {
                "savings": f"{total_tl_savings:.2f} ₺",
                "reduction": f"{total_kwh_reduction:.2f} kWh"
            }
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Sistem Hatası: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)