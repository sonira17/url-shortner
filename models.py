from sqlalchemy import Column, Integer, String ,DateTime,func
from database import Base 

class DataMapping(Base):
      __tablename__ = "url_shortner"
      id=Column(Integer, primary_key=True, index=True)
      short_code=Column(String, unique=True, index=True)
      long_url = Column(String,nullable=False)
      created_at = Column(DateTime(timezone=True), nullable=False,server_default=func.now())
      expired_at = Column(DateTime(timezone=True), nullable=True)
