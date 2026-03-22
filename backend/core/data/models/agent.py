"""
Agent ORM 模型
"""
from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.sql import func
from core.data.base import Base


class Agent(Base):
    __tablename__ = "agents"
    
    agent_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    definition_json = Column(Text, nullable=False)  # JSON 存储 AgentDefinition
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
