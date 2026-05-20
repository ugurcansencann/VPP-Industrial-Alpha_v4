# VPP-Industrial-Alpha ⚡
Virtual Power Plant (Sanal Güç Santrali) Optimizasyon, Tahmin ve Veri Yönetim Sistemi.

Bu platform; endüstriyel tesislerin enerji maliyetlerini minimize etmek için EPİAŞ piyasa verilerini, makine öğrenmesi tabanlı yük/fiyat tahminlerini ve matematiksel optimizasyon modellerini birleştiren uçtan uca bir çözümdür.

### 🚀 Teknolojiler
**Yapay Zeka & Optimizasyon:** Scikit-learn, XGBoost ve LightGBM ile ileri dönük yük ve fiyat tahminleme modelleri; PuLP doğrusal programlama kütüphanesi ile operasyonel maliyet minimizasyonu motoru.

**Derin Öğrenme Tabanlı Projeksiyon (Plan F):** PyTorch (CPU-Optimized) mimarisi kullanılarak, sistem belleğini yormayan ve geçmiş fiyat trendlerinden beslenen zaman serisi tahminleme altyapısı.

**Uygulama Sunucusu (Backend):** FastAPI (Python) tabanlı, asenkron ve yüksek performanslı API veri köprüsü.

**Veri Mühendisliği & Süreç Orkestrasyonu:** Apache Airflow ile yapay zeka modellerinin veri boru hatları (ETL), model başarı takipleri ve zamanlanmış görevlerin merkezi yönetimi.

**Veritabanı Yönetimi:** PostgreSQL ilişkisel veritabanı yapısı ve SQLAlchemy (ORM) katmanı ile milisaniye seviyesinde zaman serisi ve piyasa verisi sorgulama yeteneği.

**Hızlı Önbellekleme (Cache):** Redis entegrasyonu ile sık çağrılan piyasa takas fiyatları ve dashboard verilerinde sıfır gecikmeli yanıt süreleri.

**Konteynerleştirme ve Dağıtım:** Docker & Docker Compose mimarisi sayesinde tüm platformlardan bağımsız, izole, kaynak limitleri kontrol edilebilir ve hızlı ölçeklenebilir altyapı kurulumu.

**Özet**
- **Backend:** FastAPI (Python) - Asenkron, yüksek performanslı API mimarisi.
- **Data Engineering:** Apache Airflow - Veri boru hatları ve ETL süreçlerinin orkestrasyonu.
- **Database:** PostgreSQL (SQLAlchemy) - Zaman serisi ve ilişkisel veri yönetimi.
- **Cache:** Redis - Hızlı dashboard yanıtları ve veri önbellekleme.
- **Containerization:** Docker & Docker Compose - İzole ve ölçeklenebilir deployment.
- **ML & Optimization:** Scikit-learn, XGBoost, PuLP - Tahminleme ve maliyet minimizasyonu.

*******************************************************************
### 🛠 Öne Çıkan Özellikler

**Çok Katmanlı Risk ve Operasyon Yönetimi:** Tesis operasyonlarını piyasa gerçeklerine göre optimize eden; geleceğe yönelik fiyat projeksiyonu (Plan F), uzun vadeli stratejik planlama (Plan A) ve anlık dengesizlik/ceza yönetimi (Plan B) sekmeleri tek bir merkezden yönetilir.

**Finansal Öngörü ve Stratejik Fiyatlama (Plan F):** Serbest enerji piyasasındaki fiyat dalgalanmalarını analiz ederek, tesislerin enerji satın alma maliyetlerini düşürmek için ileriye dönük fiyat ortalamaları ve finansal öngörüler sunar.

**Maliyet Optimizasyonu & Tüketim Esnekliği (Plan A):** Tesisin üretim süreçlerini aksatmadan, hangi saatte ne kadarlık bir yükü kaydırabileceğini (kWh ve ₺ bazında) net olarak hesaplar. Tüketimin yoğun olduğu pik saatlerdeki maliyetleri minimize eden bir karar destek mekanizması sağlar.

**Anlık Dengesizlik ve Reaktif Operasyon Yönetimi (Plan B):** Gerçek zamanlı saha sayaç verileri ile piyasa fiyatlarını (PTF vs. SMF) eşzamanlı analiz eder. Tesisin şebekeye karşı yarattığı enerji açığı veya fazlasını bularak, oluşabilecek finansal cezaları anlık olarak kümülatif maliyet yönetimiyle raporlar.

**Akıllı Piyasa Yönü ve Ceza Radarı (yal0 / yat0 Kestirimi):** Piyasa takas fiyatlarının henüz kesinleşmediği kör saatlerde, şebekenin yönünü (enerji açığı veya fazlası durumunu) otomatik tahmin ederek operasyon ekibine erkenden aksiyon alma ve arbitraj fırsatlarını yakalama imkanı tanır.

**Gelişmiş Görsel Karar Destek Mekanizması:** Fiyat hareketleri ile sahadaki sapma miktarlarını (kWh) aynı grafikte hibrit olarak birleştirir. Enerji açığı (mali ceza riski) oluşturan saatleri dinamik olarak kırmızı, enerji fazlası (fırsat) yaratan saatleri ise yeşil dikey barlarla işaretleyerek operatörün hata yapma riskini sıfıra indirir.

**Merkezi İzleme & Tek Tuşla Yeniden Optimizasyon:** Yapay zeka modellerinin ticari başarı skorlarını (MAE, MAPE, $R^2$) ve sistemin genel sağlık raporunu tek bir ekranda toplar. Değişen piyasa koşullarına göre modellerin tek tuşla arka planda yeniden eğitilmesini ve kendini güncellemesini sağlar.

**Dinamik Performans ve Başarı Kıyaslaması:** Yapay zeka modelinin tahmin doğruluğu her güncellemede otomatik olarak kontrol edilir. Model kalitesindeki iyileşmeler (maliyet tasarruf potansiyelinin artması veya hata oranlarının düşmesi) ekranda anlık olarak yeşil, sapmalar ise kırmızı renkle vurgulanarak ticari risk takibi şeffaflaştırılır.

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
