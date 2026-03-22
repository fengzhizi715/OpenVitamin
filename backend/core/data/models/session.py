"""
AgentSession ORM 模型
并发优化：添加复合索引以加速查询
"""
from sqlalchemy import Column, String, Integer, Text, DateTime, Index
from sqlalchemy.sql import func
from core.data.base import Base


class AgentSession(Base):
    __tablename__ = "agent_sessions"
    
    session_id = Column(String, primary_key=True)
    agent_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    trace_id = Column(String)
    status = Column(String, nullable=False)
    step = Column(Integer, default=0, nullable=False)
    messages_json = Column(Text, nullable=False)  # JSON 存储 Message 列表
    state_json = Column(Text)  # JSON 存储 state dict
    error_message = Column(Text)
    workspace_dir = Column(Text)
    # V2.6: Execution Kernel instance ID (for event stream replay/debug)
    kernel_instance_id = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # 索引优化
    __table_args__ = (
        # 单列索引
        Index('idx_agent_sessions_user_id', 'user_id'),
        Index('idx_agent_sessions_agent_id', 'agent_id'),
        Index('idx_agent_sessions_updated_at', 'updated_at'),
        
        # 复合索引（覆盖常用查询模式）
        Index('idx_agent_sessions_user_agent', 'user_id', 'agent_id'),
        Index('idx_agent_sessions_user_updated', 'user_id', 'updated_at'),
        Index('idx_agent_sessions_user_agent_updated', 'user_id', 'agent_id', 'updated_at'),
    )
