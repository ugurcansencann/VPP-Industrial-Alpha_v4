import pandas as pd
import joblib
import os
import json
import requests
from sqlalchemy import text
from database_setup import engine # Merkezi engine kullanımı
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split

# Docker ağında 'web' servisine ulaşmak için
WEB_SERVICE_RELOAD_URL = "http://web:8000/reload-model"

def run_ml_pipeline(mode="baseline", limit=168):
    """
    mode: "baseline" (tüm veri) veya "retrain" (son n veri)
    """
    
    # SQL Sorgusu: Tarih ve saate göre kronolojik sıralama (ML için kritik)
    if mode == "baseline":
        query = text("SELECT * FROM meter_readings WHERE meter_id='MTR_00001' ORDER BY date ASC, hour ASC")
    else:
        query = text(f"SELECT * FROM meter_readings WHERE meter_id='MTR_00001' ORDER BY date ASC, hour ASC LIMIT {limit}")
    
    try:
        df = pd.read_sql(query, engine)
        if len(df) < 24: # Lag 24h için minimum veri kontrolü
            return f"Yetersiz veri (Mevcut: {len(df)})"
    except Exception as e:
        return f"Veritabanı Hatası: {str(e)}"

    # --- FEATURE ENGINEERING ---
    df['date'] = pd.to_datetime(df['date'])
    
    # Saat verisini (00:00 formatı) sayıya çevirme
    # split(':').str[0] hem '01:00' hem de '1' gibi verileri güvenle yakalar
    df['hour_int'] = df['hour'].str.split(':').str[0].astype(int)
    
    # Veriyi zaman sırasına göre kesinleştir
    df = df.sort_values(['date', 'hour_int']) 
    
    # Sayısal değer (value) kontrolü
    df['value'] = pd.to_numeric(df['value'], errors='coerce')
    df['day_of_week'] = df['date'].dt.dayofweek
    
    # Gecikmeli Veriler (Lags): Geçmiş 1 saat ve 24 saat önceki değerler
    df['lag_1'] = df['value'].shift(1)
    df['lag_24'] = df['value'].shift(24)
    
    # Shift işleminden sonra oluşan boş satırları (NaN) temizle
    df = df.dropna(subset=['lag_1', 'lag_24', 'value'])
    
    # Modelin kullanacağı sütunlar
    features = ['hour', 'day_of_week', 'lag_1', 'lag_24']
    X = df[features]
    y = df['value']

    # --- MODEL EĞİTİM & DEĞERLENDİRME ---
    # Zaman serisi olduğu için shuffle=False (Geçmişle eğit, gelecekle test et)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, shuffle=False)

    model = RandomForestRegressor(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)
    
    # Başarı metriklerini hesapla
    preds = model.predict(X_test)
    mae = mean_absolute_error(y_test, preds)
    r2 = r2_score(y_test, preds)

    # Üretim için tüm veriyle son bir kez eğit
    model.fit(X, y)
    
    # Modeli ve metrikleri diske yaz
    joblib.dump(model, "consumption_model.pkl")
    
    metrics = {
        "rmse": float(np.sqrt(mean_squared_error(y, preds))),
        "mae": float(mean_absolute_error(y, preds)),
        "r2": float(r2_score(y, preds)),
        "mape": float(np.mean(np.abs((y - preds) / y)) * 100), # Bunu da ekleyebilirsin
        "mode": mode,
        "sample_size": len(df),
        "last_train_date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    }
    
    with open("model_metrics.json", "w") as f:
        json.dump(metrics, f)

    # API'ye modelin güncellendiğini haber ver
    try:
        requests.post(WEB_SERVICE_RELOAD_URL, timeout=5)
    except:
        # Web servisi o an açık değilse pipeline'ı bozmasın
        pass

    return f"Pipeline ({mode}) tamamlandı. R2: {round(r2, 3)}, MAE: {round(mae, 3)}"

if __name__ == "__main__":
    # Docker içinde 'python train_model.py' diyerek tetiklenebilir
    print(run_ml_pipeline(mode="baseline"))
    
import pandas as pd
import joblib
import numpy as np
from xgboost import XGBRegressor
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
import os

def train_and_log_model(readings, model_dir="saved_models"):
    if not os.path.exists(model_dir):
        os.makedirs(model_dir)

    # 1. Veri Hazırlama
    df = pd.DataFrame([{"hour": int(r.hour.split(':')[0]), "val": r.value, "date": r.date} for r in readings])
    df = df.sort_values(['date', 'hour'])
    
    df['lag_1'] = df['val'].shift(1)
    df['lag_24'] = df['val'].shift(24)
    df['day_of_week'] = pd.to_datetime(df['date']).dt.dayofweek
    df = df.dropna()

    if df.empty:
        raise Exception("Eğitim için yeterli veri oluşmadı.")

    X = df[['hour', 'day_of_week', 'lag_1', 'lag_24']]
    y = df['val']

    # 2. Model ve Eğitim
    params = {
        "n_estimators": 100,
        "max_depth": 5,
        "learning_rate": 0.1,
        "objective": 'reg:squarederror',
        "random_state": 42
    }
    
    model = XGBRegressor(**params)
    model.fit(X, y)

    # 3. Metrik Hesaplama (MAPE eklendi)
    preds = model.predict(X)
    
    # Sıfıra bölme hatasını önlemek için (MAPE)
    y_array = np.array(y)
    mask = y_array != 0
    mape = np.mean(np.abs((y_array[mask] - preds[mask]) / y_array[mask])) * 100

    metrics = {
        "rmse": float(np.sqrt(mean_squared_error(y, preds))),
        "mae": float(mean_absolute_error(y, preds)),
        "r2": float(r2_score(y, preds)),
        "mape": float(mape)
    }

    # 4. Kayıt
    timestamp = pd.Timestamp.now().strftime('%Y%m%d_%H%M')
    model_path = os.path.join(model_dir, f"vpp_model_{timestamp}.pkl")
    
    joblib.dump(model, model_path)
    joblib.dump(model, "consumption_model.pkl")

    return model_path, params, metrics, list(X.columns), len(df)