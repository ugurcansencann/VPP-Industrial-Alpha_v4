from fastapi import FastAPI, Depends, HTTPException
import pandas as pd, joblib, redis, json, subprocess, os, random
from pulp import LpProblem, LpMinimize, LpVariable, lpSum, value
from fastapi.responses import HTMLResponse
# Veritabanı bileşenleri
from sqlalchemy.orm import Session
from database import engine, Base, SessionLocal
import crud
from models import MeterReading
from kpi_engine import calculate_vpp_performance

# --- VERİTABANI BAĞLANTI YÖNETİCİSİ ---
# Bu fonksiyon Depends(get_db) için gereklidir
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Tabloları oluştur (Eğer tablolar silindiyse otomatik oluşturur)
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

# --- 1. MODEL YENİDEN EĞİTİM (MLOps) ---
@app.post("/retrain")
def retrain_model():
    try:
        # train_model.py dosyasını çalıştırır
        result = subprocess.run(["python", "train_model.py"], capture_output=True, text=True)
        if result.returncode != 0:
            return {"status": "error", "message": result.stderr}
            
        global model
        model = joblib.load("consumption_model.pkl")
        cache.flushdb() 
        return {"status": "success", "message": "Model yeni piyasa verileriyle (SMF/PTF) eğitildi!"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@app.get("/model-stats")
def get_model_stats():
    try:
        with open("model_metrics.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"mae": "N/A", "r2_score": "N/A", "message": "Model henüz eğitilmedi."}

# --- 2. DİNAMİK OPTİMİZASYON (Piyasa Odaklı) ---
@app.get("/optimize")
def get_optimization(hour: int, day_of_week: int, current_price: float, smf: float = None):
    # Eğer SMF verilmemişse PTF'e eşit varsayalım
    actual_cost = smf if smf else current_price
    
    cache_key = f"opt_{hour}_{day_of_week}_{actual_cost}"
    cached_data = cache.get(cache_key)
    if cached_data:
        return json.loads(cached_data)

    if not model:
        return {"error": "Model henüz eğitilmedi."}

    # Tahmin
    input_data = pd.DataFrame([[hour, day_of_week]], columns=['hour', 'day_of_week'])
    predicted_load = model.predict(input_data)[0]
    
    # Optimizasyon (Esneklik Kapasitesi %20)
    # Eğer SMF > PTF ise sistem daha agresif yük kısar
    flexibility_limit = 0.70 if (smf and smf > current_price) else 0.80
    
    prob = LpProblem("Maliyet_Minimizasyonu", LpMinimize)
    consumption_var = LpVariable("Gercek_Tuketim", lowBound=predicted_load * flexibility_limit, upBound=predicted_load)
    prob += consumption_var * actual_cost
    prob.solve()
    
    optimized_load = value(consumption_var)
    savings = (predicted_load - optimized_load) * actual_cost
    
    result = {
        "predicted_base_load": round(predicted_load, 2),
        "optimized_load": round(optimized_load, 2),
        "potential_savings_tl": round(savings, 2),
        "market_status": "HIGH_COST" if (smf and smf > current_price) else "NORMAL"
    }
    
    cache.setex(cache_key, 3600, json.dumps(result))
    return result

# --- 3. KPI VE PERFORMANS TAKİBİ ---
@app.get("/vpp-performance/{meter_id}")
def get_vpp_metrics(meter_id: str, db: Session = Depends(get_db)):
    # Burada tek bir cihazın son verisi gerektiği için 
    # crud içindeki fonksiyonunun doğru çalıştığından emin ol
    reading = crud.get_readings(db, meter_id=meter_id)
    
    if not reading:
        raise HTTPException(status_code=404, detail="Cihaz verisi bulunamadı")

    # KPI motorunu çalıştır (Yeni SMF verisiyle)
    metrics = calculate_vpp_performance(
        actual_consumption=reading.consumption,
        actual_price=reading.price,
        smf=getattr(reading, 'smf', reading.price) # SMF yoksa PTF kullan
    )
    
    return {
        "meter_id": meter_id,
        "timestamp": reading.timestamp,
        "current_values": {
            "consumption": reading.consumption,
            "ptf": reading.price,
            "smf": getattr(reading, 'smf', None)
        },
        "kpi_metrics": metrics
    }

# --- 4. GEÇMİŞ VERİ VE DASHBOARD --- # --- REFRESH LOGIC ---
@app.get("/history")
def get_history(db: Session = Depends(get_db)):
    # CRUD metodu içindeki limit parametresini 24 olarak kullanıyoruz
    history = crud.get_readings(db, limit=24)
    
    # Dashboard grafiği soldan sağa (eskiden yeniye) aksın diye 
    # listeyi ters çevirip (Pythonic slice ile) gönderiyoruz.
    return history[::-1]

from models import MarketData, VPPForecast
@app.get("/api/v1/market-data/planA")
async def get_latest_market_data_planA(db: Session = Depends(get_db)):
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
    
    # 3. Fallback (Yarın verisi henüz manuel girilmemişse bugüne dön)
    if not ptf_results and target_date > now.date():
        target_date = now.date()
        ptf_results = crud.get_24h_data_by_type(db, target_date, 1, MarketData)
        load_results = crud.get_24h_data_by_type(db, target_date, 2, VPPForecast)

    # 4. Veri Birleştirme (Frontend'in beklediği format)
    # 24 saatlik bir sözlük oluşturarak ptf ve load'u eşleştiriyoruz
    combined = {f"{i:02d}:00": {"hour": f"{i:02d}:00", "ptf": 0.0, "load": 0.0} for i in range(24)}
    
    for r in ptf_results:
        combined[r.hour]["ptf"] = round(float(r.value), 2)
    
    for r in load_results:
        combined[r.hour]["load"] = round(float(r.value), 2)

    return {
        "status": "success",
        "date": target_date.strftime('%Y-%m-%d'),
        "is_tomorrow": target_date > now.date(),
        "data": list(combined.values())
    }

from fastapi import FastAPI, Query
from datetime import datetime, timedelta
from crud import get_24h_data_by_type 
@app.get("/api/v1/market-data/planB")
async def get_latest_market_data_planB(db: Session = Depends(get_db)):
    now = datetime.now()
    
    # 1. Hedef Tarih Belirleme (14:00 Kuralı)
    # Eğer saat 14:00'ü geçtiyse hedef yarındır, geçmediyse bugündür.
    if now.hour >= 14:
        target_date = now.date() + timedelta(days=-1)
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

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    try:
        with open("templates/index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Dashboard dosyası (templates/index.html) bulunamadı!</h1>"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)