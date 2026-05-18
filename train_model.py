import pandas as pd
import joblib
import json
import requests
import numpy as np
from xgboost import XGBRegressor
from database_setup import engine # Merkezi engine kullanımı
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score, mean_squared_error
from sklearn.model_selection import train_test_split
from models import MeterReading, MarketData
from database_setup import get_db
from sqlalchemy.orm import Session
from fastapi import Depends
import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'  # Sadece hataları göster, uyarı ve bilgilendirmeleri gizle
# Docker ağında 'web' servisine ulaşmak için
WEB_SERVICE_RELOAD_URL = "http://web:8000/reload-model"

def get_model_prediction(model_type, h, target_date, latest_actual, scaler=None):
    """
    Model tipine göre uygun giriş verisini hazırlar ve tahmini döner.
    """
    if model_type == "lstm":
        # LSTM için son 24 saatlik veriyi (Window) hazırlamak gerekir
        # Not: Basitlik adına burada son değeri tekrarlıyoruz, gerçekte son 24 saatlik liste gelmeli
        scaled_input = scaler.transform(np.array([[latest_actual.value]]))
        # LSTM input shape: (1, 24, 1) - Burada windowing mantığınıza göre düzenleyin
        # ... (Pencereleme kodunuzu buraya entegre edin)
        model = load_model("lstm_model.h5")
        # pred = model.predict(...)
        return 0.0 # Örnek döngü

    elif model_type == "expo":
        model = joblib.load("expo_model.pkl")
        # Exponential Smoothing genellikle tüm seriye göre forecast yapar
        # Burada h adım sonrasını forecast olarak alabiliriz
        return float(model.forecast(1)[0])

    else: # Default: XGBoost / RandomForest
        model = joblib.load("consumption_model.pkl")
        input_df = pd.DataFrame([[h, target_date.weekday(), latest_actual.value, latest_actual.value]], 
                                columns=['hour_int', 'day_of_week', 'lag_1', 'lag_24'])
        return float(model.predict(input_df)[0])

def calculate_mape(y_true, y_pred):
    y_true, y_pred = np.array(y_true), np.array(y_pred)
    mask = y_true != 0
    if not np.any(mask):
        return 0.0
    return np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100

def meter_forecasting_training(mode="baseline", limit=168):
    """
    mode: "baseline" (tüm veri) veya "retrain" (son n veri)
    """
    # 1. SQL Sorgusu    
    if mode == "baseline":
        sql = "SELECT * FROM meter_readings WHERE meter_id = 'MTR_00001' ORDER BY date ASC, hour ASC"
    else:
        sql = f"SELECT * FROM meter_readings WHERE meter_id = 'MTR_00001' ORDER BY date ASC, hour ASC LIMIT {limit}"

    try:
        df = pd.read_sql(text(sql), engine.connect())
    except Exception as e:
        return f"Veritabanı Hatası: {str(e)}"

    if df.empty or len(df) < 24:
        return f"Yetersiz veri (Mevcut: {len(df)})"
    
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
    features = ['hour_int', 'day_of_week', 'lag_1', 'lag_24']
    X = df[features]
    y = df['value']

    # --- MODEL EĞİTİM & DEĞERLENDİRME ---
    # Zaman serisi olduğu için shuffle=False (Geçmişle eğit, gelecekle test et)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, shuffle=False)

    model = RandomForestRegressor(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)
    
    # --- DÜZELTME 2: Metrikleri sadece test seti (X_test) üzerinden hesapla ---
    # Tüm veri üzerinden hesaplamak (overfitting riskini gizler) simülasyonu yanıltır
    preds = model.predict(X_test)
    mae_test = mean_absolute_error(y_test, preds)
    rmse_test = np.sqrt(mean_squared_error(y_test, preds))
    r2_test = r2_score(y_test, preds)
    mape_test = calculate_mape(y_test, preds)

    # Üretim için tüm veriyle son bir kez eğit
    model.fit(X, y)
    
    # Modeli ve metrikleri diske yaz
    joblib.dump(model, "consumption_model.pkl")
    
    metrics = {
        "rmse": float(rmse_test),
        "mae": float(mae_test),
        "r2": float(r2_test),
        "mape": float(mape_test),
        "mode": mode,
        "sample_size": len(df), # Artık 3190 göreceksin
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

    return f"Pipeline ({mode}) tamamlandı. R2: {round(r2_test, 3)}, MAE: {round(mae_test, 3)}, MAPE: {round(mape_test, 3)}"



def meter_forecasting_testing(readings, model_dir="saved_models"):
    if not os.path.exists(model_dir):
        os.makedirs(model_dir)

    # 1. Veri Hazırlama
    df = pd.DataFrame([{"hour_int": int(r.hour.split(':')[0]), "value": r.value, "date": r.date} for r in readings])
    df = df.sort_values(['date', 'hour_int'])
    
    df['lag_1'] = df['value'].shift(1)
    df['lag_24'] = df['value'].shift(24)
    df['day_of_week'] = pd.to_datetime(df['date']).dt.dayofweek
    df = df.dropna()

    if df.empty:
        raise Exception("Eğitim için yeterli veri oluşmadı.")

    X = df[['hour_int', 'day_of_week', 'lag_1', 'lag_24']]
    y = df['value']

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
        "r2_score": float(r2_score(y, preds)),
        "mape": float(mape)
    }

    # 4. Kayıt
    timestamp = pd.Timestamp.now().strftime('%Y%m%d_%H%M')
    model_path = os.path.join(model_dir, f"vpp_model_{timestamp}.pkl")
    
    joblib.dump(model, model_path)
    joblib.dump(model, "consumption_model.pkl")

    return model_path, params, metrics, list(X.columns), len(df)

### 
from sqlalchemy import text
def ptf_forecasting_training(mode="baseline", limit=168):
    """
    MarketData (data_typeid=1) listesini alır, lag özelliklerini hazırlar,
    XGBoost ile eğitir ve metrikleri döner.
    """
    # 1. SQL Sorgusu
    

    if mode == "baseline":
        sql = "SELECT * FROM market_data WHERE data_typeid = 1 ORDER BY date ASC, hour ASC"
    else:
        sql = f"SELECT * FROM market_data WHERE data_typeid = 1 ORDER BY date ASC, hour ASC LIMIT {limit}"

    try:
        df = pd.read_sql(text(sql), engine.connect())
    except Exception as e:
        return f"Veritabanı Hatası: {str(e)}"

    if df.empty or len(df) < 192:
        return f"Yetersiz veri (Mevcut: {len(df)})"

    # --- FEATURE ENGINEERING ---
    df['date'] = pd.to_datetime(df['date'])
    df['hour_int'] = df['hour'].str.split(':').str[0].astype(int)
    df['day_of_week'] = df['date'].dt.dayofweek
    
    df = df.sort_values(['date', 'hour_int']) 
    df['value'] = pd.to_numeric(df['value'], errors='coerce')
    # Gecikmeli Veriler
    df['lag_1'] = df['value'].shift(1)
    df['lag_24'] = df['value'].shift(24)
    df['lag_168'] = df['value'].shift(168) # 'val' düzeltildi

    # NaN temizliği
    df = df.dropna(subset=['lag_1', 'lag_24', 'lag_168', 'value'])
    
    # ÖNEMLİ: features listesinde hour_int kullanmalısın, string olan hour_str'yi değil!
    features = ['hour_int', 'day_of_week', 'lag_1', 'lag_24', 'lag_168']
    X = df[features]
    y = df['value']

    # --- MODEL EĞİTİM ---
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, shuffle=False)

     # 2. Model ve Eğitim Parametreleri
    params = {
        "n_estimators": 150, # Fiyat oynaklığı için biraz daha fazla ağaç
        "max_depth": 6,
        "learning_rate": 0.05,
        "objective": 'reg:squarederror',
        "random_state": 42
    }
    
    model = XGBRegressor(**params)
    model.fit(X_train, y_train)
    
    # --- DÜZELTME 2: Metrikleri sadece test seti (X_test) üzerinden hesapla ---
    # Tüm veri üzerinden hesaplamak (overfitting riskini gizler) simülasyonu yanıltır
    preds = model.predict(X_test)
    mae_test = mean_absolute_error(y_test, preds)
    rmse_test = np.sqrt(mean_squared_error(y_test, preds))
    r2_test = r2_score(y_test, preds)
    mape_test = calculate_mape(y_test, preds)
    # Üretim için tüm veriyle son bir kez eğit
    model.fit(X, y)
    
    # Modeli ve metrikleri diske yaz
    joblib.dump(model, "price_model.pkl")
    
    metrics = {
        "rmse": float(rmse_test),
        "mae": float(mae_test),
        "r2": float(r2_test),
        "mape": float(mape_test),
        "mode": mode,
        "sample_size": len(df), # Artık 3190 göreceksin
        "last_train_date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    }
    
    with open("model_metrics_ptf.json", "w") as f:
        json.dump(metrics, f)

    # API'ye modelin güncellendiğini haber ver
    try:
        requests.post(WEB_SERVICE_RELOAD_URL, timeout=5)
    except:
        # Web servisi o an açık değilse pipeline'ı bozmasın
        pass

    return f"Pipeline ({mode}) tamamlandı. R2: {round(r2_test, 3)}, MAE: {round(mae_test, 3)}, MAPE: {round(mape_test, 3)}"


def ptf_forecasting_testing(readings, model_dir="saved_models"):
    if not os.path.exists(model_dir):
        os.makedirs(model_dir)

    # 1. Veri Hazırlama
    df = pd.DataFrame([{"hour_int": int(r.hour.split(':')[0]), "value": r.value, "date": r.date} for r in readings])
    df = df.sort_values(['date', 'hour_int'])
    
    df['lag_1'] = df['value'].shift(1)
    df['lag_24'] = df['value'].shift(24)
    df['lag_168'] = df['value'].shift(168)
    df['day_of_week'] = pd.to_datetime(df['date']).dt.dayofweek
    df = df.dropna()

    if df.empty:
        raise Exception("Eğitim için yeterli veri oluşmadı.")

    X = df[['hour_int', 'day_of_week', 'lag_1', 'lag_24','lag_168']]
    y = df['value']

    # 2. Model ve Eğitim
    params = {
        "n_estimators": 150, # Fiyat oynaklığı için biraz daha fazla ağaç
        "max_depth": 6,
        "learning_rate": 0.05,
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
        "r2_score": float(r2_score(y, preds)),
        "mape": float(mape)
    }

    # 4. Kayıt
    timestamp = pd.Timestamp.now().strftime('%Y%m%d_%H%M')
    model_path = os.path.join(model_dir, f"vpp_model_{timestamp}.pkl")
    
    joblib.dump(model, model_path)
    joblib.dump(model, "price_model.pkl")

    return model_path, params, metrics, list(X.columns), len(df)


    


from statsmodels.tsa.holtwinters import ExponentialSmoothing

def meter_forecasting_expo_training(mode="baseline", limit=500):
    # 1. Veri Hazırlama
    sql = "SELECT value FROM meter_readings WHERE meter_id = 'MTR_00001' ORDER BY date ASC, hour ASC"
    if mode != "baseline": sql += f" LIMIT {limit}"
    
    df = pd.read_sql(text(sql), engine.connect())
    if len(df) < 48: return "Yetersiz veri."

    series = df['value'].astype(float).values
    
    # 2. Eğitim ve Test Ayrımı
    train_size = int(len(series) * 0.8)
    train, test = series[:train_size], series[train_size:]

    # 3. Model Kurulumu (24 saatlik mevsimsellik ile)
    model = ExponentialSmoothing(train, trend='add', seasonal='add', seasonal_periods=24)
    model_fit = model.fit()

    # 4. Değerlendirme
    preds = model_fit.forecast(len(test))
    metrics = {
        "rmse": float(np.sqrt(mean_squared_error(test, preds))),
        "mae": float(mean_absolute_error(test, preds)),
        "r2_score": float(r2_score(test, preds)),
        "mape": float(calculate_mape(test, preds))
    }

    # Üretim için tüm veriyle eğit
    final_model = ExponentialSmoothing(series, trend='add', seasonal='add', seasonal_periods=24).fit()
    joblib.dump(final_model, "expo_model.pkl")

    return "es_model_final.pkl", {"seasonal_periods": 24, "trend": "add"}, metrics, ["value"], len(df)

def meter_forecasting_expo_testing(readings, model_dir="saved_models"):
    # Tahmin anında modelin güncellenmesi veya kayıt altına alınması gerekirse
    # ES modelleri genellikle yeni veriyle 'update' edilmek yerine yeniden eğitilir.
    # Bu fonksiyon mevcut modelin performansını güncel veride test eder.
    series = np.array([r.value for r in readings])
    model = joblib.load("expo_model.pkl")
    
    preds = model.forecast(len(series))
    metrics = {
        "rmse": float(np.sqrt(mean_squared_error(series, preds))),
        "mae": float(mean_absolute_error(series, preds)),
        "r2_score": float(r2_score(series, preds)),
        "mape": float(calculate_mape(series, preds))
    }
    
    timestamp = pd.Timestamp.now().strftime('%Y%m%d_%H%M')
    path = os.path.join(model_dir, f"expo_model_{timestamp}.pkl")
    joblib.dump(model, path)
    
    return path, {"type": "Holt-Winters"}, metrics, ["value"], len(series)



from sklearn.preprocessing import MinMaxScaler
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import LSTM, Dense, Dropout

def meter_forecasting_lstm_training(mode="baseline", limit=1000):
    # 1. Veri Hazırlama
    sql = "SELECT value FROM meter_readings WHERE meter_id = 'MTR_00001' ORDER BY date ASC, hour ASC"
    df = pd.read_sql(text(sql), engine.connect())
    data = df['value'].values.reshape(-1, 1)

    scaler = MinMaxScaler(feature_range=(0, 1))
    scaled_data = scaler.fit_transform(data)

    # Pencereleme: 24 saat bak, 1 saat tahmin et
    def create_sequences(data, window=24):
        X, y = [], []
        for i in range(window, len(data)):
            X.append(data[i-window:i, 0])
            y.append(data[i, 0])
        return np.array(X), np.array(y)

    X, y = create_sequences(scaled_data)
    X = X.reshape((X.shape[0], X.shape[1], 1))

    # 2. Model Yapısı
    params = {"epochs": 10, "batch_size": 32, "units": 50}
    model = Sequential([
        LSTM(params["units"], return_sequences=True, input_shape=(24, 1)),
        Dropout(0.2),
        LSTM(params["units"]),
        Dense(1)
    ])
    model.compile(optimizer='adam', loss='mse')
    
    # 3. Eğitim
    model.fit(X, y, epochs=params["epochs"], batch_size=params["batch_size"], verbose=0)

    # 4. Metrikler (Eğitim verisi üzerinden basit kontrol)
    preds_scaled = model.predict(X)
    preds = scaler.inverse_transform(preds_scaled)
    actuals = scaler.inverse_transform(y.reshape(-1, 1))

    metrics = {
        "rmse": float(np.sqrt(mean_squared_error(actuals, preds))),
        "mae": float(mean_absolute_error(actuals, preds)),
        "r2_score": float(r2_score(actuals, preds)),
        "mape": float(calculate_mape(actuals, preds))
    }

    model.save("lstm_model.h5")
    joblib.dump(scaler, "lstm_model.pkl")
    
    return "lstm_model.h5", params, metrics, ["lag_1_to_24"], len(df)

def meter_forecasting_lstm_testing(readings, model_dir="saved_models"):
    # Mevcut veriyi al ve modelle test et
    df = pd.DataFrame([{"value": r.value} for r in readings])
    data = df['value'].values.reshape(-1, 1)
    
    scaler = joblib.load("lstm_model.pkl")
    model = load_model("lstm_model.h5")
    
    scaled_data = scaler.transform(data)
    # Test için en az 24 saatlik veri girişi gerekir
    if len(scaled_data) < 25: raise Exception("LSTM testi için min 25 veri lazım.")
    
    X_test = []
    for i in range(24, len(scaled_data)):
        X_test.append(scaled_data[i-24:i, 0])
    
    X_test = np.array(X_test).reshape((len(X_test), 24, 1))
    preds_scaled = model.predict(X_test)
    preds = scaler.inverse_transform(preds_scaled)
    
    actuals = data[24:] # İlk 24 saat tahmin edilemez, pencere dolmalı
    
    metrics = {
        "rmse": float(np.sqrt(mean_squared_error(actuals, preds))),
        "mae": float(mean_absolute_error(actuals, preds)),
        "r2_score": float(r2_score(actuals, preds)),
        "mape": float(calculate_mape(actuals, preds))
    }

    timestamp = pd.Timestamp.now().strftime('%Y%m%d_%H%M')
    path = os.path.join(model_dir, f"lstm_model_{timestamp}.h5")
    model.save(path)
    
    return path, {"window_size": 24}, metrics, ["sequence"], len(df)



if __name__ == "__main__":
    # Docker içinde 'python train_model.py' diyerek tetiklenebilir
    #print(run_ml_pipeline(mode="baseline"))
    #print(meter_forecasting_training(mode="baseline"))
    #print(ptf_forecasting_training(mode="baseline"))
    #print(meter_forecasting_expo_training(mode="baseline"))
    print(meter_forecasting_lstm_training(mode="baseline"))