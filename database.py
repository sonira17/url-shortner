from sqlalchemy import create_engine

from sqlalchemy.orm import sessionmaker,declarative_base

from config import settings


# creating the engine 
engine=create_engine(
    settings.sqlalchemy_string
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db=SessionLocal()
    try:
        yield db

    finally:
        db.close()