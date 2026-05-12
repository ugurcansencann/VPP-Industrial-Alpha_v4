# database_setup.py (Eklemeli Versiyon)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

SQLALCHEMY_DATABASE_URL = "postgresql://user:password@db:5432/vpp_db"

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# main.py'deki get_db'yi buraya taşıyabilirsin, böylece her yerden çağırılabilir:
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()