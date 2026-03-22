"""
SystemSetting ORM 模型
"""
from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.sql import func
from core.data.base import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"
    
    key = Column(String, primary_key=True)
    value_json = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
