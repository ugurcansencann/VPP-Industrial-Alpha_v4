# VPP-Industrial-Alpha ⚡
Virtual Power Plant (Sanal Güç Santrali) Optimizasyon ve Veri Yönetim Sistemi.

### 🚀 Teknolojiler
- **Backend:** FastAPI (Python)
- **Data Engineering:** Apache Airflow
- **Database:** PostgreSQL
- **Cache:** Redis
- **Containerization:** Docker & Docker Compose
- **ML & Optimization:** Scikit-learn, PuLP
*******************************************************************
* Plan A (Stratejik) ve Plan B (Reaktif) operasyon modülleri eklendi.
* EPİAŞ PTF ve ML bazlı tüketim tahmin simülasyonu entegre edildi.
* FastAPI backend ve Chart.js frontend veri köprüsü oluşturuldu.
* Üretim odaklı yük kaydırma karar mekanizması eklendi.

```mermaid
graph TD
    subgraph "1. Veri Kaynakları (Data Sources)"
        EP["EPİAŞ Şeffaflık (PTF Verisi)"]
        IOT["IoT Sayaç (MeterReading Tablosu)"]
        DB_HIST["Geçmiş Tüketim & Hava Durumu Verisi"]
    end

    subgraph "2. Analitik Katman (ML & Optimization Engine)"
        ML_TRAIN["Model Eğitimi (train_and_log_model)"]
        ML_FORECAST["Rolling Forecast (Python/XGBoost)"]
        OPT_ENGINE["Optimizasyon Motoru (PuLP / Maliyet Min.)"]
        SYNCHRONIZER["Sync Logic (Dashboard & Simülasyon Eşitleyici)"]
    end

    subgraph "3. Servis Katmanı (Backend - FastAPI)"
        API["FastAPI Endpointleri (PlanA & Retrain)"]
        DB_SQL["PostgreSQL (SQLAlchemy)"]
        VPP_CORE["VPP Logic (summarize_vpp_results)"]
    end

    subgraph "4. Sunum Katmanı (Frontend - Single Source of Truth)"
        UI["Dashboard (Panel A / JS)"]
        METRICS["Model Başarı Metrikleri (MAE/R2/MAPE)"]
        CHART["Zaman Serisi Grafiği (Chart.js)"]
        UNIFIED_TBL["Senkronize Operasyonel Tablo"]
    end

    %% Veri ve İşlem Akışı
    EP & IOT --> DB_SQL
    DB_SQL --> ML_TRAIN
    ML_TRAIN --> ML_FORECAST
    
    %% Yeni Senkronize Akış
    ML_FORECAST --> OPT_ENGINE
    OPT_ENGINE --> SYNCHRONIZER
    SYNCHRONIZER --> VPP_CORE
    
    %% API & UI İletişimi
    VPP_CORE <--> API
    API <--> DB_SQL
    
    %% Frontend Tekil Besleme
    API -- "JSON (Data + Metadata + Metrics)" --> UI
    UI --> METRICS
    UI --> CHART
    UI --> UNIFIED_TBL

    style SYNCHRONIZER fill:#f96,stroke:#333,stroke-width:2px
    style VPP_CORE fill:#bbf,stroke:#333,stroke-width:2px
