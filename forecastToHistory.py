from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from models import VPPMeterForecast, VPPMeterForecastHistory, VPPForecast, VPPForecastHistory

async def sync_forecasts_to_db(db: Session, forecast_results: list, simulation_id: int, forecast_type: str = "meter"):
    """
    Tahminleri önce geçmiş tablosuna (log) ekler, 
    ardından aktif dashboard tablolarını günceller.
    """
    try:
        if forecast_type == "meter":
            # 1. GEÇMİŞ TABLOSUNA EKLE (History)
            history_records = [
                VPPMeterForecastHistory(
                    target_date=item['date'],
                    target_hour=item['hour'],
                    value=item['value'],
                    meter_id=item['meter_id'],
                    simulation_id=simulation_id
                ) for item in forecast_results
            ]
            db.add_all(history_records)

            # 2. AKTİF TABLOYU GÜNCELLE (Upsert - PostgreSQL Örneği)
            for item in forecast_results:
                stmt = insert(VPPMeterForecast).values(
                    date=item['date'],
                    hour=item['hour'],
                    value=item['value'],
                    meter_id=item['meter_id']
                )
                # Eğer date, hour ve meter_id çakışırsa, sadece değeri ve updated_at'i güncelle
                stmt = stmt.on_conflict_do_update(
                    index_elements=['date', 'hour', 'meter_id'],
                    set_={'value': item['value']}
                )
                db.execute(stmt)

        elif forecast_type == "market":
            # Market (PTF/SMF) verileri için benzer mantık
            history_records = [
                VPPForecastHistory(
                    target_date=item['date'],
                    target_hour=item['hour'],
                    value=item['value'],
                    data_typeid=item['data_typeid'],
                    simulation_id=simulation_id
                ) for item in forecast_results
            ]
            db.add_all(history_records)

            for item in forecast_results:
                stmt = insert(VPPForecast).values(
                    date=item['date'],
                    hour=item['hour'],
                    value=item['value'],
                    data_typeid=item['data_typeid']
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=['date', 'hour', 'data_typeid'],
                    set_={'value': item['value']}
                )
                db.execute(stmt)

        db.commit()
    except Exception as e:
        db.rollback()
        raise e