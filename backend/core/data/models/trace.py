"""
AgentTrace ORM 模型
"""
from sqlalchemy import Column, String, Integer, Text, DateTime, Index
from sqlalchemy.sql import func
from core.data.base import Base


class AgentTrace(Base):
    __tablename__ = "agent_traces"
    
    id = Column(String, primary_key=True)
    trace_id = Column(String)
    session_id = Column(String, nullable=False)
    step = Column(Integer, nullable=False)
    event_type = Column(String, nullable=False)
    agent_id = Column(String)
    model_id = Column(String)
    tool_id = Column(String)
    input_json = Column(Text)  # JSON 存储 input_data
    output_json = Column(Text)  # JSON 存储 output_data
    duration_ms = Column(Integer)
    created_at = Column(DateTime, default=func.now())
    
    # 索引
    __table_args__ = (
        Index('idx_agent_traces_session_id', 'session_id'),
    )
