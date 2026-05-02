# VPP-Industrial-Alpha ⚡
Virtual Power Plant (Sanal Güç Santrali) Optimizasyon ve Veri Yönetim Sistemi.

### 🚀 Teknolojiler
- **Backend:** FastAPI (Python)
- **Data Engineering:** Apache Airflow
- **Database:** PostgreSQL
- **Cache:** Redis
- **Containerization:** Docker & Docker Compose
- **ML & Optimization:** Scikit-learn, PuLP

- Plan A (Stratejik) ve Plan B (Reaktif) operasyon modülleri eklendi.
- EPİAŞ PTF ve ML bazlı tüketim tahmin simülasyonu entegre edildi.
- FastAPI backend ve Chart.js frontend veri köprüsü oluşturuldu.
- Üretim odaklı yük kaydırma karar mekanizması eklendi.

```mermaid
graph TD
    subgraph "1. Veri Kaynakları (Data Sources)"
        EP["EPİAŞ Şeffaflık (PTF/SMF)"]
        IOT["IoT Sayaç / Saha Verisi"]
        DB_HIST["Geçmiş Tüketim DB"]
    end

    subgraph "2. Analitik Katman (Intelligence Layer)"
        ML["ML Tahmin Modeli (Python/XGBoost)"]
        OPT["Optimizasyon Motoru (Maliyet Min.)"]
        STRAT["Strateji Karar (Plan A/B Logic)"]
    end

    subgraph "3. Servis Katmanı (Backend Layer)"
        API["FastAPI / Python"]
        DB_SQL["PostgreSQL (SQLAlchemy)"]
        DOCKER["Docker Container"]
    end

    subgraph "4. Sunum Katmanı (Presentation Layer)"
        UI["Dashboard (HTML/JS/Chart.js)"]
        CTRL["Mod Kontrol Paneli"]
        TBL["Operasyonel Takvim"]
    end

    %% Veri Akışları
    EP --> API
    IOT --> API
    DB_HIST --> ML
    ML --> OPT
    OPT --> STRAT
    STRAT --> API
    API <--> DB_SQL
    API --> UI
    UI --> CTRL
    CTRL --> TBL
