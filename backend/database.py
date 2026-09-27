import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base


import os
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "payments.db")
DB_URL = "sqlite:///" + DB_PATH


engine = create_engine(DB_URL, echo=False, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
