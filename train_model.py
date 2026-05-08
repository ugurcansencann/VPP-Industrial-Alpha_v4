import pandas as pd
import joblib
import os
import json
import requests
from sqlalchemy import create_engine
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split

DB_URL = os.getenv("DATABASE_URL", "postgresql://user:password@db:5432/vpp_db")
WEB_SERVICE_RELOAD_URL = "http://web:8000/reload-model"

def run_ml_pipeline(mode="retrain", limit=100):
    """
    mode: "baseline" (tüm veri) veya "retrain" (son n veri)
    limit: retrain modunda kaç satır alınacağı
    """
    engine = create_engine(DB_URL)
    
    if mode == "baseline":
        query = "SELECT * FROM meter_readings where meter_id='MTR_00001' ORDER BY date DESC"
    else:
        query = f"SELECT * FROM meter_readings where meter_id='MTR_00001' ORDER BY date DESC LIMIT {limit}"
    
    try:
        df = pd.read_sql(query, engine)
        if len(df) < 20: # Split yapabilmek için minimum eşik
            return f"Yetersiz veri (Mevcut: {len(df)})"
    except Exception as e:
        return f"Hata: {str(e)}"

    # Feature Engineering (Merkezi hale getirildi)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date') # Lag verilerin doğru gelmesi için SIRALAMA ŞART
    df['day_of_week'] = df['date'].dt.dayofweek
    # [EKLENDİ] Geçmiş tüketim (Lag): Tüketim tahmininde hayati önem taşır
    df['consumption_lag_1h'] = df['value'].shift(1)
    df['consumption_lag_24h'] = df['value'].shift(24)
    #df['smf'] = df['smf'].fillna(df['price'])
    #df['price_spread'] = (df['smf'] - df['price']) / 1000
    #df['system_direction'] = df['yal'].fillna(0) - df['yat'].fillna(0)
    #df['price_norm'] = df['price'] / 1000 
    # [KRİTİK] İlk 24 satır boş (NaN) kalacaktır, bunları temizlemelisin
    df = df.dropna(subset=['consumption_lag_1h', 'consumption_lag_24h', 'value'])
    features = ['hour', 'day_of_week', 'consumption_lag_1h', 'consumption_lag_24h']
    # Eksik veri içeren satırları son bir kez temizliyoruz
    #df = df.dropna(subset=features + ['consumption'])
    X = df[features]
    y = df['value']

    # --- DATA SPLIT & EVALUATION ---
    # Veriyi %80 Eğitim, %20 Test olarak ayırıyoruz
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = RandomForestRegressor(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)
    
    # Metrik Hesaplama (R2 ve MAE)
    preds = model.predict(X_test)
    mae = mean_absolute_error(y_test, preds)
    r2 = r2_score(y_test, preds)

    # Final Modeli Tüm Veriyle Eğit (Production Readiness)
    model.fit(X, y)
    
    # Kayıt İşlemleri
    joblib.dump(model, "consumption_model.pkl")
    
    metrics = {
        "mae": round(mae, 3),
        "r2_score": round(r2, 3),
        "mode": mode,
        "sample_size": len(df),
        "last_train_date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    }
    
    with open("model_metrics.json", "w") as f:
        json.dump(metrics, f)

    # Web Servis Tetikleme
    try:
        requests.post(WEB_SERVICE_RELOAD_URL, timeout=5)
    except:
        pass

    return f"Pipeline ({mode}) tamamlandı. R2: {round(r2, 3)}, MAE: {round(mae, 3)}"

if __name__ == "__main__":
    # Manuel çalıştırmada varsayılan olarak baseline başlasın
    print(run_ml_pipeline(mode="baseline"))