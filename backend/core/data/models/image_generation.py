from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.sql import func

from core.data.base import Base


class ImageGenerationJobORM(Base):
    __tablename__ = "image_generation_jobs"

    job_id = Column(String(36), primary_key=True)
    model = Column(String(255), nullable=False, index=True)
    prompt = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, index=True)
    phase = Column(String(64), nullable=True)
    error = Column(Text, nullable=True)
    request_json = Column(JSON, nullable=False, default=dict)
    result_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=func.now(), index=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())


class ImageGenerationWarmupORM(Base):
    __tablename__ = "image_generation_warmups"

    warmup_id = Column(String(36), primary_key=True)
    model = Column(String(255), nullable=False, index=True)
    prompt = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, index=True)
    elapsed_ms = Column(Integer, nullable=True)
    output_path = Column(Text, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    request_json = Column(JSON, nullable=False, default=dict)
    result_json = Column(JSON, nullable=True)
    latest = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, nullable=False, default=func.now(), index=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
