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

class VPPForecast(Base):
    """
    Plan A için yarınki fiyat ve yük tahminlerinin saklandığı tablo.
    """
    __tablename__ = "vpp_forecasts"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False)          # Import edildiği için artık hata vermez
    hour = Column(String, nullable=False)        # "00:00" formatı için String
    expected_price = Column(Float, nullable=False) # EPİAŞ PTF verisi
    predicted_load = Column(Float, nullable=False) # ML tahmin verisi