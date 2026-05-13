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
from forecastToHistory import sync_forecasts_to_db

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
    
    # --- KRİTİK NOKTA: simulation_id Bulma ---
    # En son eğitilen modelin ID'sini alıyoruz
    last_simulation = db.query(MLModelSimulation).order_by(MLModelSimulation.run_date.desc()).first()
    sim_id = last_simulation.id if last_simulation else 1 # Hiç yoksa 1 kabul et
    # -----------------------------------------
    
    # 3. Tahmin Üretme
    day_of_week = target_date.weekday()
    lag_1h, lag_24h = recent_readings[0].value, recent_readings[23].value
    
    forecast_results = []
    for h in range(24):
        input_df = pd.DataFrame([[h, day_of_week, lag_1h, lag_24h]], 
                                columns=['hour', 'day_of_week', 'lag_1', 'lag_24'])
        prediction = float(model.predict(input_df)[0])
        # sync fonksiyonu için uygun sözlük yapısı
        forecast_results.append({
            'date': target_date,
            'hour': f"{h:02d}:00",
            'value': round(prediction, 3),
            'meter_id': meter_id
        })
    # 4. HAVUZ VE AKTİF TABLOLARI SENKRONİZE ET
    # Daha önce yazdığımız servis fonksiyonunu çağırıyoruz
    await sync_forecasts_to_db(db, forecast_results, sim_id, forecast_type="meter")

from datetime import date
async def get_calculable_target_date(db: Session, initial_date: date) -> date:
    """
    PTF verisinin mevcudiyetine göre hesaplanabilir en güncel tarihi döner.
    """
    current_date = initial_date
    # En fazla 3 gün geriye git (Sonsuz döngüyü önlemek için)
    for _ in range(3):
        ptf_exists = db.query(MarketData).filter(
            MarketData.date == current_date,
            MarketData.data_typeid == 1
        ).first()
        
        if ptf_exists:
            return current_date
        current_date -= timedelta(days=1)
        
    return current_date # Hiç veri yoksa yine de en son bakılanı dön

@app.get("/api/v1/market-data/planA")
async def get_latest_market_data_planA(db: Session = Depends(get_db)):
    if model is None:
        raise HTTPException(status_code=500, detail="ML Modeli (.pkl) bulunamadı.")

    # 1. Ham tarih belirleme (Mimariyi bozmaz)
    base_date = (datetime.now().date() + timedelta(days=1)) if datetime.now().hour >= 14 else datetime.now().date()
    
    # 2. Profesyonel Kontrol: Veri mevcudiyetine göre nihai tarihi al
    target_date = await get_calculable_target_date(db, base_date)

    meter_id = "MTR_00001"

    try:
        # --- BÖLÜM 1: TAHMİN ÜRET VE KAYDET ---
        # --- ADIM 1: KONTROL VE TAHMİN (Sadece gerekiyorsa çalışır) ---
        await ensure_forecast_exists(db, target_date, meter_id)

        # --- BÖLÜM 2: VERİ BİRLEŞTİRME & SERVİS İLE OPTİMİZASYON ---
        results = db.query(
            VPPMeterForecast.hour,
            VPPMeterForecast.predicted_value.label("forecast_load"), # Tahmin Kutusu (Yeşil)
            MeterReading.value.label("actual_load"),                 # Gerçek Kutusu (Mor)
            MarketData.value.label("ptf")                            # PTF Kutusu
        ).outerjoin(
            MeterReading, and_(
                MeterReading.date == VPPMeterForecast.date,
                MeterReading.hour == VPPMeterForecast.hour,
                MeterReading.meter_id == VPPMeterForecast.meter_id
            )
        ).outerjoin(
            MarketData, and_(
                MarketData.date == VPPMeterForecast.date,
                MarketData.hour == VPPMeterForecast.hour,
                MarketData.data_typeid == 1
            )
        ).filter(
            VPPMeterForecast.date == target_date, 
            VPPMeterForecast.meter_id == meter_id
        ).order_by(VPPMeterForecast.hour.asc()).all()
        dashboard_data = []
        for r in results:
            # 1. Hangi veriyi kullanacağız? (Önce Gerçek, yoksa Tahmin)
            # 13 Mayıs 15:00'e kadar actual_load dolu gelecek, sonrası None olacak.
            actual_val = float(r.actual_load) if r.actual_load is not None else None
            forecast_val = float(r.forecast_load) if r.forecast_load is not None else 0.0
            
            # Tablo ve hesaplama için öncelik gerçek veride
            final_load = actual_val if actual_val is not None else forecast_val
            
            ptf_val = float(r.ptf) if r.ptf is not None else 0.0
            
            # Optimizasyon servisini nihai veriyle çağır
            opt_results = calculate_vpp_optimization(final_load, ptf_val, smf=None)
            
            dashboard_data.append({
                "hour": r.hour,
                "ptf": ptf_val,
                "actual_load": actual_val,    # Görseldeki 'Gerçek' kutusu için
                "forecast_load": forecast_val, # Görseldeki 'Tahmin' kutusu için
                "display_load": final_load,    # Tabloda ana değer olarak görünecek olan
                "is_forecast": r.actual_load is None, # Saat bazlı dinamik kontrol, # Frontend'de rengi ayırt etmek için yardımcı bayrak
                **opt_results
            })

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
        target_date = now.date() + timedelta(days=1)
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
        target_date = now.date() + timedelta(days=1)
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

from train_model import train_price_model
@app.post("/api/v1/ptf-forecast")
async def price_forecasting(db: Session = Depends(get_db)):
    try:
        now = datetime.now()
        target_date = now.date()
        
        # 1. Eğitim Verisini Çek (MarketData - data_typeid=1: Gerçekleşen PTF)
        # Modelin lag_168 özelliğini kurabilmesi için geçmiş veriyi çekiyoruz
        ptf_readings = db.query(MarketData).filter(MarketData.data_typeid == 1).all()
        
        if not ptf_readings or len(ptf_readings) < 169:
            raise Exception("Eğitim ve lag hesaplaması için yeterli geçmiş veri bulunamadı.")
            
        # train_model.py içindeki fonksiyon ile eğitimi başlat
        path, params, metrics, features, count = train_price_model(ptf_readings)

        # Loglama için tarih aralığı
        start_dt = min(r.date for r in ptf_readings)
        end_dt = max(r.date for r in ptf_readings)
        
        # 2. Blok Tahmin İçin Referans Verileri Hazırlama
        active_model = joblib.load("price_model.pkl")
        
        # PTF'de her saat için lag farklıdır. 
        # Döngü içinde her seferinde DB'ye gitmemek için son 8 günü DataFrame'e çekelim.
        history_limit = now - timedelta(days=8)
        recent_data = db.query(MarketData).filter(
            MarketData.data_typeid == 1,
            MarketData.date >= history_limit.date()
        ).all()
        
        ref_df = pd.DataFrame([{"date": r.date, "hour": int(r.hour.split(':')[0]), "val": r.value} for r in recent_data])
        ref_df = ref_df.sort_values(['date', 'hour'])

        # Rolling yerine 00:00 - 23:00 arası tüm gün için tahmin üretip DB'ye yazıyoruz
        forecast_results = []
        # 00:00'dan 23:00'e kadar tüm günün tahminini yapıyoruz
        for h in range(0, 24):
            # Lag değerlerini ref_df üzerinden dinamik çekelim (daha isabetli tahmin için)
            # Eğer o anki lag verisi henüz yoksa (blok veri gecikmesi), bulabildiği en son veriyi alır
            try:
                lag_1 = ref_df.iloc[-1]['val'] 
                lag_24 = ref_df[ref_df['hour'] == h].iloc[-1]['val'] # Dünkü aynı saat
                lag_168 = ref_df[ref_df['hour'] == h].iloc[-7]['val'] # Geçen haftaki aynı saat
            except:
                # Veri eksikliği durumunda fallback
                lag_1 = lag_24 = lag_168 = ref_df.iloc[-1]['val']

            input_df = pd.DataFrame([[
                h, 
                target_date.weekday(), 
                lag_1, 
                lag_24, 
                lag_168
            ]], columns=['hour', 'day_of_week', 'lag_1', 'lag_24', 'lag_168'])
            
            pred_value = float(active_model.predict(input_df)[0])
            
            # DB Güncelleme
            db.query(VPPForecast).filter(
                VPPForecast.date == target_date,
                VPPForecast.hour == f"{h:02d}:00",
                VPPForecast.data_typeid == 1
            ).update({"value": round(pred_value, 2)})
            
            forecast_results.append(pred_value)

        # 3. ML Performans Logu
        new_log = MLModelSimulation(
            run_date = datetime.now(),
            model_name = os.path.basename(path),
            model_path = path,
            rmse = metrics["rmse"],
            mae = metrics["mae"],
            r2_score = metrics["r2_score"],
            mape = metrics.get("mape"),
            sample_count = count,
            training_start_date = min(r.date for r in ptf_readings),
            training_end_date = max(r.date for r in ptf_readings),
            hyperparameters = params,
            features_used = features,
            training_notes = "PTF Günlük Blok Tahmin. Lag_24 ve Lag_168 dinamik referans alındı."
        )
        
        db.add(new_log)
        db.commit() 
        
        return {
            "status": "success",
            "daily_average": round(sum(forecast_results)/24, 2),
            "updated_date": str(target_date)
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"PTF İşlem Hatası: {str(e)}")
    
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
from train_model import run_ml_pipeline, train_price_model
from forecast_opt_service import generate_and_save_forecasts

@app.post("/vpp/retrain")
def retrain_model():
    """Dashboard'dan gelen 'Eğit' isteği. 
    Limitli veri (örn: son 168 saat) ile .pkl'yi tazeler."""
    result = train_price_model(mode="ptftrain", limit=168)
    return {"status": "Model Güncellendi", "metrics": result}

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
from sqlalchemy.orm import Session, aliased
from datetime import datetime
import joblib
import pandas as pd
@app.post("/api/v1/retrain-and-refresh")
async def retrain_and_refresh(db: Session = Depends(get_db)):
    try:
        now = datetime.now()
        target_date = now.date()
        meter_id = "MTR_00001"

        # 1. MODEL EĞİTİMİ (Mevcut mantığın - Değişmedi)
        readings = db.query(MeterReading).filter(MeterReading.meter_id == meter_id).all()
        if not readings:
            raise Exception("Eğitim verisi bulunamadı.")
            
        path, params, metrics, features, count = train_and_log_model(readings)
        start_dt = min(r.date for r in readings)
        end_dt = max(r.date for r in readings)

        # 2. YENİ TAHMİNLERİ OLUŞTUR VE KAYDET
        active_model = joblib.load("consumption_model.pkl")
        latest_actual = db.query(MeterReading).filter(MeterReading.meter_id == meter_id)\
                          .order_by(MeterReading.date.desc(), MeterReading.hour.desc()).first()

        for h in range(now.hour + 1, 24):
            hour_str = f"{h:02d}:00"
            input_df = pd.DataFrame([[h, target_date.weekday(), latest_actual.value, latest_actual.value]], 
                                    columns=['hour', 'day_of_week', 'lag_1', 'lag_24'])
            new_pred = float(active_model.predict(input_df)[0])
            
            db.query(VPPMeterForecast).filter(
                VPPMeterForecast.date == target_date,
                VPPMeterForecast.hour == hour_str,
                VPPMeterForecast.meter_id == meter_id
            ).update({"predicted_value": round(new_pred, 3)})

        db.commit() # Veritabanı artık en güncel tahminlere sahip

        # 3. KRİTİK ADIM: DASHBOARD (planA) İLE AYNI SQL SORGUSU
        # Burada actual_load_table yerine doğrudan MeterReading kullanıyoruz (planA'daki gibi)
        results = db.query(
            VPPMeterForecast.hour,
            VPPMeterForecast.predicted_value.label("forecast_load"),
            MeterReading.value.label("actual_load"),
            MarketData.value.label("ptf")
        ).outerjoin(
            MeterReading, (MeterReading.date == VPPMeterForecast.date) & 
                          (MeterReading.hour == VPPMeterForecast.hour) & 
                          (MeterReading.meter_id == VPPMeterForecast.meter_id)
        ).outerjoin(
            MarketData, (MarketData.date == VPPMeterForecast.date) & 
                        (MarketData.hour == VPPMeterForecast.hour) & 
                        (MarketData.data_typeid == 1) # Sadece PTF
        ).filter(
            VPPMeterForecast.date == target_date,
            VPPMeterForecast.meter_id == meter_id
        ).order_by(VPPMeterForecast.hour.asc()).all()
                
        # 4. HESAPLAMA DÖNGÜSÜ (Dashboard ile 1:1 Aynı)
        dashboard_data = []
        for r in results:
            actual_val = float(r.actual_load) if r.actual_load is not None else None
            forecast_val = float(r.forecast_load) if r.forecast_load is not None else 0.0
            
            # Dashboard mantığındaki öncelik sırası:
            final_load = actual_val if actual_val is not None else forecast_val
            ptf_val = float(r.ptf) if r.ptf is not None else 0.0
            
            # Aynı optimizasyon fonksiyonu
            opt_results = calculate_vpp_optimization(final_load, ptf_val, smf=None)
            
            dashboard_data.append({
                "hour": r.hour,
                "ptf": ptf_val,
                "actual_load": actual_val,
                "forecast_load": forecast_val,
                "display_load": final_load,
                "is_forecast": r.actual_load is None,
                **opt_results
            })
        
        summary = summarize_vpp_results(dashboard_data)

        # 5. SİMÜLASYON KAYDI
        new_log = MLModelSimulation(
            run_date = datetime.now(),
            model_name=os.path.basename(path),
            model_path=path,
            rmse=metrics["rmse"],
            mae=metrics["mae"],
            r2_score=metrics["r2_score"],
            mape=metrics.get("mape"),
            sample_count=count,
            training_start_date=start_dt,
            training_end_date=end_dt,
            simulated_total_reduction=summary["total_reduction_kwh"],
            simulated_total_savings=summary["total_savings_tl"],
            hyperparameters=params,
            features_used=features,
            training_notes=f"Kullanıcı tetiklemeli senkronize update. Saat: {now.hour}:00"
        )
        
        db.add(new_log)
        db.commit()
        
        # 6. FRONTEND'E DÖNÜŞ (Artık fetch('/api/v1/market-data/planA') gerektirmez)
        return {
            "status": "success",
            "metrics": metrics,            
            "metadata": {"target_date": target_date.isoformat(), **summary},
            "data": dashboard_data,
            "simulation_id": new_log.id # JS tarafında takip için
        }

    except Exception as e:
        db.rollback()
        print(f"HATA DETAYI: {str(e)}") # Terminalden takip için
        raise HTTPException(status_code=500, detail=f"Sistem Hatası: {str(e)}")
    
from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from database import engine # Mevcut engine bağlantın

@app.get("/api/v1/last-simulation-results")
async def get_last_simulation():
    # Veritabanından en son başarılı simülasyonun metriklerini çekiyoruz
    # Not: Tablo adın ve sütun isimlerin farklıysa burayı güncelle
    query = text("""SELECT mae, mape, rmse, r2_score, id FROM ml_model_simulations ORDER BY run_date DESC LIMIT 1""")
    
    try:
        with engine.connect() as conn:
            result = conn.execute(query).fetchone()
            
            if result:
                return {
                    "status": "success",
                    "metrics": {
                        "mae": result.mae,
                        "mape": result.mape,
                        "rmse": result.rmse,
                        "r2_score": result.r2_score
                    },
                    "id": result.id
                }
            else:
                return {
                    "status": "error",
                    "message": "Henüz kayıtlı bir simülasyon bulunamadı."
                }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)