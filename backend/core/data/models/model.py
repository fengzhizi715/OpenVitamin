"""
Model 和 ModelConfig ORM 模型
"""
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from core.data.base import Base


class Model(Base):
    __tablename__ = "models"
    
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    model_type = Column(String, default="llm")
    provider = Column(String, nullable=False)
    provider_model_id = Column(String, nullable=False)
    runtime = Column(String, nullable=False)
    base_url = Column(String)
    capabilities_json = Column(Text)  # JSON 存储
    context_length = Column(Integer)
    device = Column(String)
    quantization = Column(String)
    size = Column(String)
    format = Column(String)
    source = Column(String)
    family = Column(String)
    version = Column(String)
    description = Column(Text)
    tags_json = Column(Text)  # JSON 存储
    metadata_json = Column(Text)  # JSON 存储
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # 关系
    config = relationship("ModelConfig", back_populates="model", uselist=False, cascade="all, delete-orphan")


class ModelConfig(Base):
    __tablename__ = "model_configs"
    
    model_id = Column(String, ForeignKey("models.id", ondelete="CASCADE"), primary_key=True)
    chat_params_json = Column(Text)  # JSON 存储
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # 关系
    model = relationship("Model", back_populates="config")
