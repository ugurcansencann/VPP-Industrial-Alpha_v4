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
### 🛠 Öne Çıkan Özellikler

**Çok Katmanlı Operasyon Modülleri:** Fiyat projeksiyonu sağlayan Plan F (Fiyat Tahmini), stratejik Plan A ve anlık tepki odaklı Plan B modülleri entegre edildi.

- **Fiyat Tahmin (Plan F):** EPİAŞ PTF verilerini analiz ederek tahmin edilen ve gerçekleşen fiyat ortalamalarını sunar. Enerji satın alma stratejileri için finansal öngörü sağlar.

- **Maliyet Optimizasyonu (Plan A):** Yük kaydırma potansiyelini (kWh ve TL bazında) hesaplar. ML tahminlerini kullanarak operasyonel verimliliği maksimize eden "Stratejik Analiz" modülünü besler.

- **Dengesizlik Yönetimi (Plan B):** "Response" modu olarak da adlandırılır. Anlık spread değerlerini ve saha sapmalarını takip ederek, reaktif aksiyonlarla finansal riskleri minimize eder.Kontrol Paneli & Model Metrikleri: Sistemin "sağlık raporunu" sunar. Airflow entegrasyonu ile modelin başarı skorlarını ($R^2$, MAE, MAPE) canlı olarak izler ve tek tuşla modeli yeniden eğitme (Retrain) imkanı sunar.

- **Gelişmiş Tahmin Simülasyonu:** EPİAŞ PTF verileri ve ML tabanlı tüketim tahminleri kullanılarak "Rolling Forecast" mekanizması oluşturuldu.

**Single Source of Truth (SSoT):** FastAPI backend ve Chart.js frontend arasında kurulan senkronize veri köprüsü ile dashboard ve simülasyon sonuçları arasında tam tutarlılık sağlandı.

**Akıllı Yük Kaydırma:** Enerji fiyatlarının tepe yaptığı saatlerdeki yükü, düşük fiyatlı veya yenilenebilir üretimin yoğun olduğu saatlere kaydıran optimizasyon motoru eklendi.

```mermaid
graph LR
    subgraph "1. Veri Kaynakları"
        direction TB
        EP["EPİAŞ (PTF)"]
        IOT["IoT Sayaç"]
        AF["Airflow ETL"]
        REDIS[("Redis Cache")]
        EP & IOT --> AF
    end

    subgraph "2. Analitik Katman"
        direction TB
        ML_T["Model Eğitimi"]
        ML_F["Tahmin (Load/Fiyat)"]
        OPT["Optimizasyon (PuLP)"]
        ML_T --> ML_F --> OPT
    end

    subgraph "3. Servis Katmanı"
        direction TB
        API["FastAPI"]
        DB[(PostgreSQL)]
        SYNC["Sync Logic"]
        CORE["VPP Logic"]
        DB <--> API
        SYNC --> CORE
    end

    subgraph "4. Sunum Katmanı"
        direction TB
        UI["Dashboard"]
        MET["Metrikler"]
        CH["Chart.js"]
        UI --> MET & CH
    end

    %% Katmanlar Arası Yatay Akış
    AF --> DB
    DB --> ML_T
    OPT --> SYNC
    CORE --> API
    API --> UI

    style SYNC fill:#f96,stroke:#333,stroke-width:2px
    style CORE fill:#bbf,stroke:#333,stroke-width:2px
    style REDIS fill:#ff9999,stroke:#333
