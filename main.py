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

async def ensure_meter_forecast_exists(db: Session, target_date, meter_id):
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
    last_simulation = db.query(MLModelSimulation).filter(MLModelSimulation.forecast_typeid == 2).order_by(MLModelSimulation.run_date.desc()).first()
    sim_id = last_simulation.id if last_simulation else 1 # Hiç yoksa 1 kabul et
    # -----------------------------------------
    
    # 3. Tahmin Üretme
    day_of_week = target_date.weekday()
    lag_1h, lag_24h = recent_readings[0].value, recent_readings[23].value
    
    forecast_results = []
    for h in range(24):
        input_df = pd.DataFrame([[h, day_of_week, lag_1h, lag_24h]], 
                                columns=['hour_int', 'day_of_week', 'lag_1', 'lag_24'])
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


async def ensure_ptf_forecast_exists(db: Session, target_date):
    """
    Piyasa Takas Fiyatı (PTF) için tahmin üretir ve veritabanına kaydeder.
    """
    # 1. Mevcut veri kontrolü (MarketData tablosunda data_typeid=2 tahmini temsil ediyorsa veya ilgili tablo)
    # Not: VPPMarketForecast tablonuzun adını projenize göre kontrol edin.
    existing_count = db.query(VPPForecast).filter(
        VPPForecast.date == target_date,
        VPPForecast.data_typeid == 1
    ).count()

    if existing_count >= 24:
        return # Veri zaten var.

    # 2. Geçmiş Verileri Çekme (PTF için lag_1, lag_24 ve lag_168 gerekli)
    # En az 168 saatlik geçmiş veri lazım (7 gün)
    recent_market_data = db.query(MarketData).filter(MarketData.data_typeid == 1)\
        .order_by(MarketData.date.desc(), MarketData.hour.desc()).limit(169).all()

    if len(recent_market_data) < 168:
        raise Exception("PTF tahmini için yeterli geçmiş veri (168 saat) yok.")

    # 3. sim_id Bulma (Model metriklerinden veya son simülasyondan)
    last_simulation = db.query(MLModelSimulation).filter(MLModelSimulation.forecast_typeid == 1).order_by(MLModelSimulation.run_date.desc()).first()
    sim_id = last_simulation.id if last_simulation else 1 # Hiç yoksa 1 kabul et

    # 4. Tahmin Üretme
    day_of_week = target_date.weekday()
    
    # Lag değerlerini belirle (En son kayıt lag_1'dir)
    lag_1 = float(recent_market_data[0].value)
    lag_24 = float(recent_market_data[23].value)
    lag_168 = float(recent_market_data[167].value)
    
    forecast_results = []
    
    # Not: 'price_model.pkl' dosyasının yüklü olduğundan emin olun (joblib.load)
    # ptf_model = joblib.load("price_model.pkl")

    for h in range(24):
        # Eğitimdeki kolon isimleriyle birebir aynı (hour_int)
        input_df = pd.DataFrame([[h, day_of_week, lag_1, lag_24, lag_168]], 
                                columns=['hour_int', 'day_of_week', 'lag_1', 'lag_24', 'lag_168'])
        
        # Tahmin yap
        prediction = float(model.predict(input_df)[0])
        
        forecast_results.append({
            'date': target_date,
            'hour': f"{h:02d}:00", # Tablo yapınıza göre 'hour' veya 'hour_int'
            'value': round(prediction, 3),
            'data_typeid': 1 # Fiyat verisi olduğunu belirtir
        })

    # 5. Kaydet ve Senkronize Et
    # forecast_type="ptf" veya "market" olarak senkronizasyon servisine gönder
    await sync_forecasts_to_db(db, forecast_results, sim_id, forecast_type="ptf")

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
        await ensure_meter_forecast_exists(db, target_date, meter_id)

        # --- BÖLÜM 2: VERİ BİRLEŞTİRME & SERVİS İLE OPTİMİZASYON ---
        results = db.query(
            VPPMeterForecast.hour,
            VPPMeterForecast.value.label("forecast_load"), # Tahmin Kutusu (Yeşil)
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

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime, timedelta

@app.get("/api/v1/market-data/planB")
async def get_latest_market_data_planB(db: Session = Depends(get_db)):
    
    # 1. Hedef Tarih Belirleme (14:00 Kuralı)
    base_date = (datetime.now().date() + timedelta(days=0)) if datetime.now().hour >= 14 else datetime.now().date()
    
    # 2. Profesyonel Kontrol: Veri mevcudiyetine göre nihai tarihi al
    target_date = await get_calculable_target_date(db, base_date)
    
    meter_id = "MTR_00001"
    
    try:
        # --- ADIM 1: TAHMİN MEVCUDİYET KONTROLÜ ---
        await ensure_meter_forecast_exists(db, target_date, meter_id)
        
        # --- ADIM 2: TEK SORGULU (SINGLE QUERY) İLİŞKİSEL BİRLEŞTİRME MİMARİSİ ---
        # MarketData tablosunu hem PTF (data_typeid=1) hem de SMF (data_typeid=3) için iki kez joinliyoruz.
        from sqlalchemy.orm import aliased
        MarketDataPTF = aliased(MarketData, name="market_data_ptf")
        MarketDataSMF = aliased(MarketData, name="market_data_smf")
        
        results = db.query(
            VPPMeterForecast.hour,
            VPPMeterForecast.value.label("forecast_load"),    # Tahmin Yükü
            MeterReading.value.label("actual_load"),          # Gerçek Yük (Sayaç)
            MarketDataPTF.value.label("ptf"),                 # PTF (type_id=1)
            MarketDataSMF.value.label("smf")                  # SMF (type_id=3)
        ).outerjoin(
            MeterReading, and_(
                MeterReading.date == VPPMeterForecast.date,
                MeterReading.hour == VPPMeterForecast.hour,
                MeterReading.meter_id == VPPMeterForecast.meter_id
            )
        ).outerjoin(
            MarketDataPTF, and_(
                MarketDataPTF.date == VPPMeterForecast.date,
                MarketDataPTF.hour == VPPMeterForecast.hour,
                MarketDataPTF.data_typeid == 1
            )
        ).outerjoin(
            MarketDataSMF, and_(
                MarketDataSMF.date == VPPMeterForecast.date,
                MarketDataSMF.hour == VPPMeterForecast.hour,
                MarketDataSMF.data_typeid == 3
            )
        ).filter(
            VPPMeterForecast.date == target_date,
            VPPMeterForecast.meter_id == meter_id
        ).order_by(VPPMeterForecast.hour.asc()).all()
        
        # --- ADIM 3: FALLBACK MEKANİZMASI ---
        # Eğer veri dönmediyse ve hedef tarih yarın ise bugüne güvenli dönüş yap
        if not results and target_date > datetime.now().date():
            target_date = datetime.now().date()
            results = db.query(
                VPPMeterForecast.hour,
                VPPMeterForecast.value.label("forecast_load"),
                MeterReading.value.label("actual_load"),
                MarketDataPTF.value.label("ptf"),
                MarketDataSMF.value.label("smf")
            ).outerjoin(
                MeterReading, and_(
                    MeterReading.date == VPPMeterForecast.date,
                    MeterReading.hour == VPPMeterForecast.hour,
                    MeterReading.meter_id == VPPMeterForecast.meter_id
                )
            ).outerjoin(
                MarketDataPTF, and_(
                    MarketDataPTF.date == VPPMeterForecast.date,
                    MarketDataPTF.hour == VPPMeterForecast.hour,
                    MarketDataPTF.data_typeid == 1
                )
            ).outerjoin(
                MarketDataSMF, and_(
                    MarketDataSMF.date == VPPMeterForecast.date,
                    MarketDataSMF.hour == VPPMeterForecast.hour,
                    MarketDataSMF.data_typeid == 3
                )
            ).filter(
                VPPMeterForecast.date == target_date,
                VPPMeterForecast.meter_id == meter_id
            ).order_by(VPPMeterForecast.hour.asc()).all()

        # --- ADIM 4: VERİ PARSE VE SÖZLÜK YAPILANDIRMASI ---
        dashboard_data = []
        
        # 24 saatlik boşluk kalmaması için baz şablon oluşturuyoruz
        combined_map = {f"{i:02d}:00": {
            "hour": f"{i:02d}:00", 
            "ptf": 0.0, 
            "smf": 0.0,
            "sistem_yonu": "DENGEDE",
            "load": 0.0,            
            "actual_load": None, 
            "forecast_load": 0.0, 
            "display_load": 0.0, 
            "is_forecast": True
        } for i in range(24)}
        
        for r in results:
            if r.hour in combined_map:
                actual_val = float(r.actual_load) if r.actual_load is not None else None
                forecast_val = float(r.forecast_load) if r.forecast_load is not None else 0.0
                
                # Öncelik her zaman gerçek veride
                final_load = actual_val if actual_val is not None else forecast_val
                
                ptf_val = round(float(r.ptf), 2) if r.ptf is not None else 0.0
                raw_smf = float(r.smf) if r.smf is not None else 0.0
                
                # --- [YENİ] SMF TAHMİN / KESTİRİM MOTORU (YAL0/YAT0 MANTIĞI) ---
                if raw_smf == 0.0:
                    current_hour_int = int(r.hour.split(':')[0])
                    
                    # Akşam pik saatleri (17:00 - 22:00) genelde sistem enerji açığına (YAL) düşer
                    if 17 <= current_hour_int <= 22:
                        sistem_yonu = "YAL"
                        smf_val = round(ptf_val * 1.18, 2)  # PTF'in %18 üzerinde ceza fiyatı tahmini
                    # Gece ve sabaha karşı seansları genelde enerji fazlasına (YAT) kayar
                    elif 0 <= current_hour_int <= 6:
                        sistem_yonu = "YAT"
                        smf_val = round(ptf_val * 0.82, 2)  # PTF'in %18 altında fırsat fiyatı tahmini
                    else:
                        sistem_yonu = "DENGEDE"
                        smf_val = ptf_val
                else:
                    smf_val = round(raw_smf, 2)
                    sistem_yonu = "YAL" if smf_val > ptf_val else ("YAT" if smf_val < ptf_val else "DENGEDE")
                
                combined_map[r.hour] = {
                    "hour": r.hour,
                    "ptf": ptf_val,
                    "smf": smf_val,
                    "sistem_yonu": sistem_yonu,
                    "load": final_load,         # frontend map döngüsündeki item.load için
                    "actual_load": actual_val,
                    "forecast_load": forecast_val,
                    "display_load": final_load,
                    "is_forecast": actual_val is None
                }
                
        dashboard_data = list(combined_map.values())

        return {
            "status": "success",
            "date": target_date.strftime('%Y-%m-%d'),
            "is_tomorrow": target_date > datetime.now().date(),
            "data": dashboard_data
        }

    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}


@app.get("/api/v1/market-data/planF")
async def get_latest_market_data_planF(db: Session = Depends(get_db)):

    if model is None:
        raise HTTPException(status_code=500, detail="ML Modeli (.pkl) bulunamadı.")

    # 1. Ham tarih belirleme (Mimariyi bozmaz)
    base_date = (datetime.now().date() + timedelta(days=1)) if datetime.now().hour >= 14 else datetime.now().date()
    
    # 2. Profesyonel Kontrol: Veri mevcudiyetine göre nihai tarihi al
    target_date = await get_calculable_target_date(db, base_date)
    try:
        # --- BÖLÜM 1: TAHMİN ÜRET VE KAYDET ---
        # --- ADIM 1: KONTROL VE TAHMİN (Sadece gerekiyorsa çalışır) ---
        await ensure_ptf_forecast_exists(db, target_date)
        
        # 2. Verileri Çek
        ptf_results = crud.get_24h_data_by_type(db, target_date, 1, MarketData)
        predicted_ptf_results = crud.get_24h_data_by_type(db, target_date, 1, VPPForecast)

        # 3. Fallback
        if not ptf_results and target_date > datetime.now().date():
            target_date = datetime.now().date()
            ptf_results = crud.get_24h_data_by_type(db, target_date, 1, MarketData)
            predicted_ptf_results = crud.get_24h_data_by_type(db, target_date, 1, VPPForecast)

        dashboard_data = []
        # Saatlik döngü ile planA mimarisinde veri oluşturma
        for i in range(24):
            hour_str = f"{i:02d}:00"
            
            # Gerçek PTF verisini bul
            actual_r = next((r for r in ptf_results if r.hour == hour_str), None)
            actual_val = float(actual_r.value) if actual_r else 0.0
            
            # Tahmin PTF verisini bul
            forecast_r = next((r for r in predicted_ptf_results if r.hour == hour_str), None)
            forecast_val = float(forecast_r.value) if forecast_r else 0.0
            
            # --- KRİTİK DÜZELTMELER ---
            dashboard_data.append({
                "hour": hour_str,
                "ptf": actual_val,             # Gerçek PTF (Mavi Çizgi)
                "forecast_ptf": forecast_val,  # Tahmin PTF (Sarı Tablo / Kırmızı Çizgi)
                "display_ptf": actual_val if actual_val >= 0 else forecast_val,
                "is_forecast": True,           # PLAN F'de her zaman True yaparak görseli zorla
                "mae": round(abs(actual_val - forecast_val), 2) if actual_val > 0 else 0.0
            })

        # Metadata ve yapı planA ile senkronize edildi
        return {
            "status": "success",
            "metadata": {
                "target_date": target_date.isoformat(),
                "total_reduction_kwh": 0.0, 
                "total_savings_tl": 0.0
            },
            "data": dashboard_data # Frontend artık bu yapıyı tanıyacak
        }
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}
    
from database_setup import get_db
from train_model import ptf_forecasting_training, ptf_forecasting_testing
@app.post("/vpp/ptf-forecasting-training")
def ptf_forecasting_trprocess():
    """Dashboard'dan gelen 'Eğit' isteği. 
    Limitli veri (örn: son 168 saat) ile .pkl'yi tazeler."""
    result = ptf_forecasting_training(mode="baseline",limit=168)
    return {"status": "Model Güncellendi", "metrics": result}

@app.post("/api/v1/retrain-and-refresh-planF")
async def price_forecasting(db: Session = Depends(get_db)):
    try:
        # 1. Ham tarih belirleme (Mimariyi bozmaz)
        base_date = (datetime.now().date() + timedelta(days=1)) if datetime.now().hour >= 14 else datetime.now().date()
    
        # 2. Profesyonel Kontrol: Veri mevcudiyetine göre nihai tarihi al
        target_date = await get_calculable_target_date(db, base_date)
            
        # 1. MODEL EĞİTİMİ (Mevcut mantığın - Değişmedi)
        actualptf_values = db.query(MarketData).filter(MarketData.data_typeid == 1).all()
        if not actualptf_values:
            raise Exception("Eğitim verisi bulunamadı.")
        

        start_dt = min(r.date for r in actualptf_values)
        end_dt = max(r.date for r in actualptf_values)

        # 2. YENİ TAHMİNLERİ OLUŞTUR VE KAYDET
        # Modeli eğit
        path, params, metrics, features, count = ptf_forecasting_testing(actualptf_values)
        active_model = joblib.load("price_model.pkl")
        # 2. Referans Verileri Hazırla (Lag hesapları için son 8 gün)
        history_limit = datetime.now() - timedelta(days=8)
        recent_data = db.query(MarketData).filter(
            MarketData.data_typeid == 1,
            MarketData.date >= history_limit.date()
        ).all()
        
        ref_df = pd.DataFrame([{"date": r.date, "hour": int(r.hour.split(':')[0]), "val": r.value} for r in recent_data])
        ref_df = ref_df.sort_values(['date', 'hour'])

        
        # predict verisi hazırlama, tahmin oluşturma ve db'ye kaydetme
        for h in range(0, 24):
            hour_str = f"{h:02d}:00"
            try:
                lag_1 = ref_df.iloc[-1]['val'] 
                lag_24 = ref_df[ref_df['hour'] == h].iloc[-1]['val']
                lag_168 = ref_df[ref_df['hour'] == h].iloc[-7]['val']
            except:
                lag_1 = lag_24 = lag_168 = ref_df.iloc[-1]['val']

            input_df = pd.DataFrame([[h, target_date.weekday(), lag_1, lag_24, lag_168]], 
                                    columns=['hour_int', 'day_of_week', 'lag_1', 'lag_24', 'lag_168'])
            
            pred_value = float(active_model.predict(input_df)[0])
            final_val = round(pred_value, 2)
            
            # VPPForecast Tablosunu Güncelle (data_typeid=1: PTF Tahmini)
            # Not: Kayıt yoksa create, varsa update mantığı için db.merge veya filter.update kullanılabilir
            # --- UPSERT MANTIĞI BAŞLANGIÇ ---
            # Önce bu saat için kayıt var mı diye bakıyoruz
            existing_forecast = db.query(VPPForecast).filter(
                VPPForecast.date == target_date,
                VPPForecast.hour == hour_str,
                VPPForecast.data_typeid == 1
            ).first()

            if existing_forecast:
                # Varsa sadece değerini güncelle
                existing_forecast.value = final_val
                print(f"Güncellendi: {hour_str} -> {final_val}")
            else:
                # Yoksa yeni bir satır oluştur (Tablon boş olduğu için burası çalışacak)
                new_entry = VPPForecast(
                    date=target_date,
                    hour=hour_str,
                    value=final_val,
                    data_typeid=1
                )
                db.add(new_entry)
                print(f"Yeni Kayıt Oluşturuldu: {hour_str} -> {final_val}")
            
            db.commit() 
            # --- UPSERT MANTIĞI BİTİŞ --- # Veritabanı artık en güncel tahminlere sahip

        # 3. KRİTİK ADIM: DASHBOARD (planA) İLE AYNI SQL SORGUSU
        # Burada actual_load_table yerine doğrudan MeterReading kullanıyoruz (planA'daki gibi)
        results = db.query(
            MarketData.hour,
            VPPForecast.value.label("forecast_ptf"), # Tahmin edilen fiyat
            MarketData.value.label("actual_ptf")    # Gerçekleşen fiyat
        ).outerjoin(
            VPPForecast, 
            (VPPForecast.date == MarketData.date) & 
            (VPPForecast.hour == MarketData.hour) & 
            (VPPForecast.data_typeid == 1) # Sadece Fiyat Tahminleri
        ).filter(
            MarketData.date == target_date,
            MarketData.data_typeid == 1      # Sadece Gerçek PTF verisi
        ).order_by(MarketData.hour.asc()).all()

        dashboard_data = []
        for r in results:
            actual_val = float(r.actual_ptf) if r.actual_ptf is not None else None
            forecast_val = float(r.forecast_ptf) if r.forecast_ptf is not None else 0.0
                
            # Dashboard mantığındaki öncelik sırası:
            final_ptf = actual_val if actual_val is not None else forecast_val
            ptf_val = float(r.actual_ptf) if r.actual_ptf is not None else 0.0
                
            dashboard_data.append({
                "hour": r.hour,
                "ptf": ptf_val,
                "forecast_ptf": forecast_val,
                "display_ptf": final_ptf,
                "is_forecast": True,  # Plan F modunda tüm tahminleri 'true' işaretle
                "mae": abs(ptf_val - forecast_val) if ptf_val > 0 else 0                
            })

        # 3. ML Performans Logu (MLModelSimulation Tablosuna)
        new_log = MLModelSimulation(
            run_date = datetime.now(),
            model_name = os.path.basename(path),
            model_path = path,
            forecast_typeid=1,  # PTF için 1, Meter için 2
            rmse = metrics.get("rmse", 0),
            mae = metrics.get("mae", 0),
            r2_score = metrics.get("r2") if metrics.get("r2") is not None else metrics.get("r2_score", 0),
            mape = metrics.get("mape"),
            sample_count = count,
            training_start_date = start_dt,
            training_end_date = end_dt,
            hyperparameters = params,
            features_used = features,
            training_notes = "Plan F: PTF Tahmin ve Simülasyonu başarıyla tamamlandı."
        )
        
        db.add(new_log)
        db.commit() 
        
        # 6. FRONTEND'E DÖNÜŞ (Artık fetch('/api/v1/market-data/planA') gerektirmez)
        return {
            "status": "success",
            "metrics": metrics,            
            "metadata": {"target_date": target_date.isoformat(),
                        "total_reduction_kwh": 0.0, 
                        "avg_reduction_kwh": 0.0,
                        "total_savings_tl": 0.0,
                        "avg_savings_tl": 0.0
                        },
            "data": dashboard_data,
            "simulation_id": new_log.id # JS tarafında takip için
        }

    except Exception as e:
        db.rollback()
        print(f"HATA DETAYI: {str(e)}") # Terminalden takip için
        raise HTTPException(status_code=500, detail=f"Sistem Hatası: {str(e)}")
    


# --- 1. MODEL YENİDEN EĞİTİM (MLOps) ---
from fastapi import APIRouter, Depends
from train_model import meter_forecasting_training, meter_forecasting_testing

@app.post("/vpp/meter-forecasting-training")
def meter_forecasting_trprocess():
    """Dashboard'dan gelen 'Eğit' isteği. 
    Limitli veri (örn: son 168 saat) ile .pkl'yi tazeler."""
    result = meter_forecasting_training(mode="baseline",limit=168)
    return {"status": "Model Güncellendi", "metrics": result}

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, aliased
from datetime import datetime
import joblib
import pandas as pd
from train_model import get_model_prediction, meter_forecasting_expo_testing, meter_forecasting_lstm_testing
@app.post("/api/v1/retrain-and-refresh-planA")
async def retrain_and_refresh(model_type: str = "baseline", db: Session = Depends(get_db)):
    
    try:
        # 1. Ham tarih belirleme (Mimariyi bozmaz)
        base_date = (datetime.now().date() + timedelta(days=1)) if datetime.now().hour >= 14 else datetime.now().date()
        
        # 2. Profesyonel Kontrol: Veri mevcudiyetine göre nihai tarihi al
        target_date = await get_calculable_target_date(db, base_date)
        meter_id = "MTR_00001"
        
        # 1. MODEL EĞİTİMİ (Mevcut mantığın - Değişmedi)
        readings = db.query(MeterReading).filter(MeterReading.meter_id == meter_id).all()
        if not readings:
            raise Exception("Eğitim verisi bulunamadı.")
            
        start_dt = min(r.date for r in readings)
        end_dt = max(r.date for r in readings)

        # 2. SEÇİLEN MODELE GÖRE EĞİTİM (Dinamik Seçim)
        if model_type == "expo":
            path, params, metrics, features, count = meter_forecasting_expo_testing(readings)
        elif model_type == "lstm":
            path, params, metrics, features, count = meter_forecasting_lstm_testing(readings)
        else:
            path, params, metrics, features, count = meter_forecasting_testing(readings)

        # 3. TAHMİNLERİ OLUŞTURMA (Loop İçinde Model Ayrımı)
        # Scaler sadece LSTM için gerekebilir
        scaler = joblib.load("lstm_model.pkl") if model_type == "lstm" else None

        latest_actual = db.query(MeterReading).filter(MeterReading.meter_id == meter_id)\
                          .order_by(MeterReading.date.desc(), MeterReading.hour.desc()).first()
        
        # predict verisi hazırlama, tahmin oluşturma ve db'ye kaydetme
        for h in range(datetime.now().hour + 1, 24):
            hour_str = f"{h:02d}:00"
            new_pred = get_model_prediction(model_type, h, target_date, latest_actual, scaler)
            
            db.query(VPPMeterForecast).filter(
                VPPMeterForecast.date == target_date,
                VPPMeterForecast.hour == hour_str,
                VPPMeterForecast.meter_id == meter_id
            ).update({"value": round(new_pred, 3)})

        db.commit() # Veritabanı artık en güncel tahminlere sahip

        # 4. DASHBOARD VERİSİNİ HAZIRLA (Aynı SQL Sorgusu)
        # Burada actual_load_table yerine doğrudan MeterReading kullanıyoruz (planA'daki gibi)
        results = db.query(
            VPPMeterForecast.hour,
            VPPMeterForecast.value.label("forecast_load"),
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
            forecast_typeid=2,  # PTF için 1, Meter için 2
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
            training_notes=f"Model: {model_type.upper()} | Saat: {datetime.now().hour}:00"
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
async def get_last_simulation(db: Session = Depends(get_db)):
    # Veritabanından en son başarılı simülasyonun metriklerini çekiyoruz
    # Not: Tablo adın ve sütun isimlerin farklıysa burayı güncelle
    query = db.query(
        MLModelSimulation.mae, MLModelSimulation.mape, MLModelSimulation.rmse,
        MLModelSimulation.r2_score, MLModelSimulation.id
    ).order_by(MLModelSimulation.run_date.desc()).first()
    
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


# --- 4. GEÇMİŞ VERİ VE DASHBOARD --- # --- REFRESH LOGIC ---
@app.get("/history")
def get_history(db: Session = Depends(get_db)):
    # CRUD metodu içindeki limit parametresini 24 olarak kullanıyoruz
    history = crud.get_readings(db, limit=24)
    
    # Dashboard grafiği soldan sağa (eskiden yeniye) aksın diye 
    # listeyi ters çevirip (Pythonic slice ile) gönderiyoruz.
    return history[::-1]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)