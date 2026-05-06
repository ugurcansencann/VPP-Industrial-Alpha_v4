import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Date
from database import Base

class MeterReading(Base):
    __tablename__ = "meter_readings"
    __table_args__ = {'extend_existing': True} 

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, nullable=False)
    consumption = Column(Float, nullable=False) 
    price = Column(Float, nullable=False)
    meter_id = Column(String, nullable=False)
    smf = Column(Float, nullable=True)
    yal = Column(Float, nullable=True)
    yat = Column(Float, nullable=True)

from sqlalchemy import Column, Integer, String, Date, Float, ForeignKey, UniqueConstraint
from database import Base

class DataType(Base):
    __tablename__ = "data_types"
    id = Column(Integer, primary_key=True, index=True)
    dataname = Column(String(50), unique=True, nullable=False) # PTF, LOAD, SMF
    value = Column(Integer, unique=True, nullable=False)    # 1, 2, 3

class VPPForecast(Base):
    __tablename__ = "vpp_forecasts"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False)
    hour = Column(String(5), nullable=False)
    datatype_id = Column(Integer, ForeignKey("data_types.value"))
    value = Column(Float, nullable=False)

    __table_args__ = (UniqueConstraint('date', 'hour', 'datatype_id', name='_date_hour_type_uc'),)


from sqlalchemy import Column, Integer, String, Float, Date, DateTime, UniqueConstraint
from sqlalchemy.sql import func

class MarketData(Base):
    __tablename__ = "market_data"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False)
    hour = Column(String(5), nullable=False)
    datatype_id = Column(Integer, ForeignKey("data_types.value"))
    value = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Veritabanı seviyesinde benzersizlik kısıtlaması
    __table_args__ = (
        UniqueConstraint('date', 'hour', 'datatype_id', name='_date_hour_name_uc'),
    )