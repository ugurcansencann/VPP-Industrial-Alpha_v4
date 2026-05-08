import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Date
from database import Base

from sqlalchemy import Column, Integer, String, Float, Date, ForeignKey
from sqlalchemy.orm import relationship

class MeterReading(Base):
    __tablename__ = "meter_readings"
    __table_args__ = {'extend_existing': True} 

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False)      # Tarih formatında (YYYY-MM-DD)
    hour = Column(String(5), nullable=False)   # 0-23 arası saat bilgisi
    data_typeid = Column(Integer, nullable=False) # Veri tipi (1: Tüketim, 2: Fiyat, 3: SMF vb.)
    value = Column(Float, nullable=False)    # Ölçülen değer
    
    # meter_id'yi artık yabancı anahtar (FK) olarak kullanıyoruz
    meter_id = Column(String, ForeignKey("meters.meter_id"), nullable=False)
    
    # İlişki tanımlama (Opsiyonel: Meter tablosuna erişim sağlar)
    meter = relationship("Meter", back_populates="readings")

from sqlalchemy import Column, String
from sqlalchemy.orm import relationship

class Meter(Base):
    __tablename__ = "meters"
    __table_args__ = {'extend_existing': True}

    # "meter_id" anahtar sütun olarak kalıyor (Örn: MTR_001)
    meter_id = Column(Integer, primary_key=True, index=True) 
    
    # Sayacın adı (Örn: "Mavişehir_Konut_45")
    meter_name = Column(String, nullable=False) 
    
    # Yeni eklenen sayaç tipi sütunu (Örn: "Mesken", "Ticari", "Sanayi")
    meter_typename = Column(String, nullable=False)

    # İlişki tanımlama: MeterReading tablosundaki 'meter' ilişkisi ile eşleşir
    readings = relationship("MeterReading", back_populates="meter", cascade="all, delete-orphan")

from sqlalchemy import Column, Integer, String, Date, Float, ForeignKey, UniqueConstraint
from database import Base

class DataType(Base):
    __tablename__ = "data_types"
    id = Column(Integer, primary_key=True, index=True)
    data_typename = Column(String(50), unique=True, nullable=False) # PTF, LOAD, SMF
    value = Column(Integer, unique=True, nullable=False)    # 1, 2, 3

class VPPForecast(Base):
    __tablename__ = "vpp_forecasts"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False)
    hour = Column(String(5), nullable=False)
    data_typeid = Column(Integer, ForeignKey("data_types.value"))
    value = Column(Float, nullable=False)

    __table_args__ = (UniqueConstraint('date', 'hour', 'data_typeid', name='_date_hour_type_uc'),)


from sqlalchemy import Column, Integer, String, Float, Date, DateTime, UniqueConstraint
from sqlalchemy.sql import func

class MarketData(Base):
    __tablename__ = "market_data"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False)
    hour = Column(String(5), nullable=False)
    data_typeid = Column(Integer, ForeignKey("data_types.value"))
    value = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Veritabanı seviyesinde benzersizlik kısıtlaması
    __table_args__ = (
        UniqueConstraint('date', 'hour', 'data_typeid', name='_date_hour_name_uc'),
    )