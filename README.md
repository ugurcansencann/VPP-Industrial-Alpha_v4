# VPP-Industrial-Alpha ⚡
Virtual Power Plant (Sanal Güç Santrali) Optimizasyon, Tahmin ve Veri Yönetim Sistemi.

Bu platform; endüstriyel tesislerin enerji maliyetlerini minimize etmek için EPİAŞ piyasa verilerini, makine öğrenmesi tabanlı yük/fiyat tahminlerini ve matematiksel optimizasyon modellerini birleştiren uçtan uca bir çözümdür.

### 🚀 Teknolojiler
- **Backend:** FastAPI (Python) - Asenkron, yüksek performanslı API mimarisi.
- **Data Engineering:** Apache Airflow - Veri boru hatları ve ETL süreçlerinin orkestrasyonu.
- **Database:** PostgreSQL (SQLAlchemy) - Zaman serisi ve ilişkisel veri yönetimi.
- **Cache:** Redis - Hızlı dashboard yanıtları ve veri önbellekleme.
- **Containerization:** Docker & Docker Compose - İzole ve ölçeklenebilir deployment.
- **ML & Optimization:** Scikit-learn, XGBoost, PuLP - Tahminleme ve maliyet minimizasyonu.

*******************************************************************
🛠 Öne Çıkan Özellikler
**Çok Katmanlı Operasyon Modülleri:** Stratejik Plan A, anlık tepki odaklı Plan B ve fiyat projeksiyonu sağlayan Plan F (Fiyat Tahmini) modülleri entegre edildi.
**Gelişmiş Tahmin Simülasyonu:** EPİAŞ PTF verileri ve ML tabanlı tüketim tahminleri kullanılarak "Rolling Forecast" mekanizması oluşturuldu.
**Single Source of Truth (SSoT):** FastAPI backend ve Chart.js frontend arasında kurulan senkronize veri köprüsü ile dashboard ve simülasyon sonuçları arasında tam tutarlılık sağlandı.
**Akıllı Yük Kaydırma:** Enerji fiyatlarının tepe yaptığı saatlerdeki yükü, düşük fiyatlı veya yenilenebilir üretimin yoğun olduğu saatlere kaydıran optimizasyon motoru eklendi.

```mermaid
graph TD
    subgraph "1. Veri Kaynakları & Orkestrasyon"
        EP["EPİAŞ Şeffaflık (PTF Verisi)"]
        IOT["IoT Sayaç (MeterReading)"]
        AF["Apache Airflow (ETL Pipeline)"]
        REDIS[("Redis Cache")]
    end

    subgraph "2. Analitik Katman (Intelligence)"
        ML_TRAIN["Model Eğitimi (XGBoost)"]
        PLAN_F["Plan F (Fiyat Tahminleme)"]
        ML_FORECAST["Tüketim (Rolling Forecast)"]
        OPT_ENGINE["Optimizasyon (PuLP / Maliyet Min.)"]
    end

    subgraph "3. Servis Katmanı (Backend - FastAPI)"
        API["FastAPI Endpointleri"]
        DB_SQL[("PostgreSQL")]
        SYNCHRONIZER["Sync Logic (SSoT)"]
        VPP_CORE["VPP Logic & Summarizer"]
    end

    subgraph "4. Sunum Katmanı (Frontend)"
        UI["Dashboard (Plan A/B/F Control)"]
        METRICS["ML Metrikleri (MAE/R2/MAPE)"]
        CHART["Zaman Serisi Analizi (Chart.js)"]
    end

    %% Veri Akışları
    EP & IOT --> AF
    AF --> DB_SQL
    DB_SQL --> ML_TRAIN
    ML_TRAIN --> ML_FORECAST & PLAN_F
    
    %% Optimizasyon ve Senkronizasyon
    ML_FORECAST & PLAN_F --> OPT_ENGINE
    OPT_ENGINE --> SYNCHRONIZER
    SYNCHRONIZER --> VPP_CORE
    
    %% API & UI
    VPP_CORE <--> API
    API <--> REDIS
    API <--> DB_SQL
    
    API -- "JSON (Unified Data)" --> UI
    UI --> METRICS & CHART
    
    style SYNCHRONIZER fill:#f96,stroke:#333,stroke-width:2px
    style VPP_CORE fill:#bbf,stroke:#333,stroke-width:2px
    style REDIS fill:#ff9999,stroke:#333
