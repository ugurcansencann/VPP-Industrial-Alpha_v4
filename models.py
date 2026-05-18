import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Date, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from database_setup import Base  # main'den değil buradan al
from sqlalchemy.sql import func
# Hafızayı temizle (Hatanın kökünü kazır)
Base.metadata.clear()




class Meter(Base):
    __tablename__ = "meters"
    __table_args__ = {'extend_existing': True}

    # "meter_id" anahtar sütun olarak kalıyor (Örn: MTR_001)
    meter_id = Column(Integer, primary_key=True) ##, index=True    
    # Sayacın adı (Örn: "Mavişehir_Konut_45")
    meter_name = Column(String, nullable=False)     
    # Yeni eklenen sayaç tipi sütunu (Örn: "Mesken", "Ticari", "Sanayi")
    meter_typename = Column(String, nullable=False)
    # İlişki tanımlama: MeterReading tablosundaki 'meter' ilişkisi ile eşleşir
    readings = relationship("MeterReading", back_populates="meter", cascade="all, delete-orphan")

class DataType(Base):
    __tablename__ = "data_types"
    id = Column(Integer, primary_key=True)#, index=True
    data_typename = Column(String(50), unique=True, nullable=False) # PTF, LOAD, SMF
    value = Column(Integer, unique=True, nullable=False)    # 1, 2, 3

class ForecastType(Base):
    __tablename__ = "forecast_types"

    id = Column(Integer, primary_key=True, index=True)
    forecast_typename = Column(String(100), nullable=False, unique=True)

class VPPMeterForecast(Base):
    __tablename__ = "vpp_meter_forecasts"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False)
    hour = Column(String(5), nullable=False)
    value = Column(Float, nullable=False) # Modelin ürettiği saf tahmin
    meter_id = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now()) # Güncellemede tetiklenir


class VPPForecast(Base):
    """Sistem geneli (PTF vb.) en güncel tahminler"""
    __tablename__ = "vpp_forecasts"
    
    id = Column(Integer, primary_key=True)#, index=True
    date = Column(Date, nullable=False)
    hour = Column(String(5), nullable=False)
    data_typeid = Column(Integer, ForeignKey("data_types.value"))
    value = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (UniqueConstraint('date', 'hour', 'data_typeid', name='_date_hour_type_uc'),)


# --- GEÇMİŞ / HAVUZ TABLOLARI (PERFORMANS ANALİZİ İÇİN) ---

class VPPMeterForecastHistory(Base):
    """Sayaç bazlı tahminlerin tüm geçmişi"""
    __tablename__ = "vpp_meter_forecast_history"
    
    id = Column(Integer, primary_key=True)
    target_date = Column(Date, nullable=False)
    target_hour = Column(String(5), nullable=False)
    predicted_value = Column(Float, nullable=False)
    meter_id = Column(String, ForeignKey("meters.meter_id"), nullable=False)
    simulation_id = Column(Integer, ForeignKey("ml_model_simulations.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class VPPForecastHistory(Base):
    """Piyasa/Sistem tahminlerinin (PTF/SMF) tüm geçmişi"""
    __tablename__ = "vpp_forecast_history"
    
    id = Column(Integer, primary_key=True)
    target_date = Column(Date, nullable=False)
    target_hour = Column(String(5), nullable=False)
    predicted_value = Column(Float, nullable=False)
    data_typeid = Column(Integer, ForeignKey("data_types.value"), nullable=False)
    simulation_id = Column(Integer, ForeignKey("ml_model_simulations.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# --- DİĞER TABLOLAR ---
class MeterReading(Base):
    __tablename__ = "meter_readings"
    # extend_existing satırını SİLDİK

    id = Column(Integer, primary_key=True, index=True) # PK geri geldi
    date = Column(Date, nullable=False)
    hour = Column(String(5), nullable=False)
    data_typeid = Column(Integer, nullable=False)
    meter_id = Column(String, ForeignKey("meters.meter_id"), nullable=False)
    value = Column(Float, nullable=False)    
    
    meter = relationship("Meter", back_populates="readings")

class MarketData(Base):
    __tablename__ = "market_data"

    id = Column(Integer, primary_key=True)#, index=True
    date = Column(Date, nullable=False)
    hour = Column(String(5), nullable=False)
    data_typeid = Column(Integer, ForeignKey("data_types.value"))
    value = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Veritabanı seviyesinde benzersizlik kısıtlaması
    __table_args__ = (UniqueConstraint('date', 'hour', 'data_typeid', name='_date_hour_name_uc'),)


from sqlalchemy import Column, Integer, String, Float, DateTime, JSON
from datetime import datetime

class MLModelSimulation(Base):
    __tablename__ = "ml_model_simulations"

    id = Column(Integer, primary_key=True, index=True)
    run_date = Column(DateTime, nullable=False) # Deneyin yapıldığı an
    forecast_typeid = Column(Integer, ForeignKey("forecast_types.id"), nullable=False)
    model_name = Column(String, nullable=False)
    model_path = Column(String, nullable=False)
    
    # Metrikler
    rmse = Column(Float, nullable=False)
    mae = Column(Float, nullable=False)
    r2_score = Column(Float, nullable=False)
    mape = Column(Float, nullable=True)
    
    # Kapsamlı Veriler
    sample_count = Column(Integer, nullable=False) # Kaç satır veriyle eğitildi?
    training_start_date = Column(DateTime)
    training_end_date = Column(DateTime)
    
    # Finansal Öngörü
    simulated_total_savings = Column(Float) # Toplam TL tasarruf
    simulated_total_reduction = Column(Float) # Toplam kWh kısıntı
    
    # Konfigürasyon
    hyperparameters = Column(JSON)
    features_used = Column(JSON) # Örn: ["hour", "day_of_week", "lag_1h"]
    training_notes = Column(String)

    forecast_type = relationship("ForecastType")