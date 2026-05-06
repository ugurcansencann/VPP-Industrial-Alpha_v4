from database import SessionLocal
import os, random, sys, requests, crud
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta


# Proje yolları
sys.path.append('/app') 

# API Ayarları
EPIAS_API_KEY = os.getenv("EPIAS_API_KEY", "YOUR_API_KEY_HERE")
BASE_URL = "https://seffaflik.epias.com.tr/api/v1"
# HEADERS eksikti, eklendi
HEADERS = {
    "X-API-KEY": EPIAS_API_KEY,
    "Content-Type": "application/json"
}

default_args = {
    'owner': 'vpp_architect',
    'start_date': datetime(2026, 4, 1),
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

def get_epias_data(endpoint, params):
    try:
        response = requests.get(f"{BASE_URL}/{endpoint}", headers=HEADERS, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"EPİAŞ API Hatası ({endpoint}): {e}")
        return None

# --- GÖREV 1: PTF Çekimi ---
def fetch_real_ptf(**kwargs):
    today = datetime.now().strftime("%Y-%m-%d")
    params = {"startDate": today, "endDate": today}
    data = get_epias_data("markets/mcp", params)
    if data and 'items' in data:
        current_hour = datetime.now().hour
        return data['items'][current_hour]['price']
    return round(random.uniform(2000, 2500), 2) # API hatasında simülasyona düşer

# --- GÖREV 2: SMF Çekimi ---
def fetch_real_smf(**kwargs):
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    params = {"startDate": date_str, "endDate": date_str}
    data = get_epias_data("markets/smp", params)
    if data and 'items' in data:
        return data['items'][-1]['smp']
    return round(random.uniform(1800, 2800), 2)

# --- GÖREV 3: YAL/YAT Talimatları (Yeni eklendi) ---
def fetch_real_instructions(**kwargs):
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    params = {"startDate": date_str, "endDate": date_str}
    data = get_epias_data("markets/uamyat-yal", params)
    if data and 'items' in data:
        last = data['items'][-1]
        return {
            "yal": last.get('yalAmount', 0),
            "yat": last.get('yatAmount', 0)
        }
    return {"yal": 0, "yat": 0}

# --- GÖREV 4: IoT Tüketimi ---
def fetch_iot_consumption(**kwargs):
    current_hour = datetime.now().hour
    base_load = 120.0 if (current_hour >= 19 or current_hour <= 6) else 10.0
    return round(base_load + random.uniform(-2.0, 2.0), 2)

# --- GÖREV 5: Birleştir ve Kaydet ---
def merge_and_store(ti, **kwargs):
    ptf = ti.xcom_pull(task_ids='get_ptf_price')
    smf = ti.xcom_pull(task_ids='get_smf_price')
    inst = ti.xcom_pull(task_ids='get_instructions')
    consumption = ti.xcom_pull(task_ids='get_iot_load')
    
    db = SessionLocal()
    try:
        # CRUD fonksiyonuna SMF, YAL, YAT parametrelerini eklediğimizi varsayıyoruz
        crud.create_meter_reading(
            db=db,
            timestamp=datetime.now(),
            meter_id="AYDIN_OSB_LIGHT_01",
            consumption=consumption,
            price=ptf,
            smf=smf,
            yal=inst['yal'],
            yat=inst['yat']
        )
        print(f"VERİ SETİ TAMAMLANDI: PTF:{ptf} | SMF:{smf} | YAL:{inst['yal']}")
    finally:
        db.close()

with DAG('vpp_osb_modular_pipeline_v36', 
         default_args=default_args,
         schedule_interval=timedelta(minutes=1), 
         catchup=False) as dag:

    t1 = PythonOperator(task_id='get_ptf_price', python_callable=fetch_real_ptf)
    t2 = PythonOperator(task_id='get_smf_price', python_callable=fetch_real_smf)
    t3 = PythonOperator(task_id='get_instructions', python_callable=fetch_real_instructions)
    t4 = PythonOperator(task_id='get_iot_load', python_callable=fetch_iot_consumption)
    t5 = PythonOperator(task_id='save_to_postgresql', python_callable=merge_and_store)

    # 4 paralel koldan veri çekilir, t5'te birleşir
    [t1, t2, t3, t4] >> t5