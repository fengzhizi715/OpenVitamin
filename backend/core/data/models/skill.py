"""
Skill ORM 模型
"""
from sqlalchemy import Column, String, Text, Integer, DateTime
from sqlalchemy.sql import func
from core.data.base import Base


class Skill(Base):
    __tablename__ = "skills"
    
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    category = Column(String)
    type = Column(String, nullable=False)  # prompt, tool, composite, workflow
    definition = Column(Text, nullable=False)  # JSON 存储
    input_schema = Column(Text, nullable=False)  # JSON 存储
    enabled = Column(Integer, default=1)  # SQLite 用 INTEGER 表示布尔
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
