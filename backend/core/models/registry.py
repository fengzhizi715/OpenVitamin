"""
模型注册中心 (ORM 版本)
"""
import json
from typing import List, Optional, Any, Dict

from sqlalchemy.dialects.sqlite import insert

from core.data.base import db_session
from core.data.models.model import Model, ModelConfig
from log import logger
from core.models.descriptor import ModelDescriptor


class ModelRegistry:
    """模型注册中心（使用 SQLAlchemy ORM）"""

    def upsert_model(self, descriptor: ModelDescriptor) -> None:
        """注册或更新模型"""
        capabilities_json = json.dumps(descriptor.capabilities)
        tags_json = json.dumps(descriptor.tags)
        metadata_json = json.dumps(descriptor.metadata)

        with db_session() as db:
            stmt = insert(Model).values(
                id=descriptor.id,
                name=descriptor.name,
                model_type=descriptor.model_type,
                provider=descriptor.provider,
                provider_model_id=descriptor.provider_model_id,
                runtime=descriptor.runtime,
                base_url=descriptor.base_url,
                capabilities_json=capabilities_json,
                context_length=descriptor.context_length,
                device=descriptor.device,
                quantization=descriptor.quantization,
                size=descriptor.size,
                format=descriptor.format,
                source=descriptor.source,
                family=descriptor.family,
                version=descriptor.version,
                description=descriptor.description,
                tags_json=tags_json,
                metadata_json=metadata_json,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "name": stmt.excluded.name,
                    "model_type": stmt.excluded.model_type,
                    "provider": stmt.excluded.provider,
                    "provider_model_id": stmt.excluded.provider_model_id,
                    "runtime": stmt.excluded.runtime,
                    "base_url": stmt.excluded.base_url,
                    "capabilities_json": stmt.excluded.capabilities_json,
                    "context_length": stmt.excluded.context_length,
                    "device": stmt.excluded.device,
                    "quantization": stmt.excluded.quantization,
                    "size": stmt.excluded.size,
                    "format": stmt.excluded.format,
                    "source": stmt.excluded.source,
                    "family": stmt.excluded.family,
                    "version": stmt.excluded.version,
                    "description": stmt.excluded.description,
                    "tags_json": stmt.excluded.tags_json,
                    "metadata_json": stmt.excluded.metadata_json,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            db.execute(stmt)

    def get_model(self, model_id: str) -> Optional[ModelDescriptor]:
        """根据 ID 获取模型描述符"""
        with db_session() as db:
            model = db.query(Model).filter(Model.id == model_id).first()
            if model:
                return self._orm_to_descriptor(model)
        return None

    def list_models(
        self, provider: Optional[str] = None, model_type: Optional[str] = None
    ) -> List[ModelDescriptor]:
        """列出所有已注册的模型"""
        with db_session() as db:
            query = db.query(Model)
            if provider:
                query = query.filter(Model.provider == provider)
            if model_type:
                query = query.filter(Model.model_type == model_type)
            models = query.all()
            return [self._orm_to_descriptor(m) for m in models]

    def _orm_to_descriptor(self, model: Model) -> ModelDescriptor:
        """ORM 对象转 ModelDescriptor"""
        return ModelDescriptor(
            id=model.id,
            name=model.name,
            model_type=model.model_type or "llm",
            provider=model.provider,
            provider_model_id=model.provider_model_id,
            runtime=model.runtime,
            base_url=model.base_url,
            capabilities=json.loads(model.capabilities_json or "[]"),
            context_length=model.context_length,
            device=model.device,
            quantization=model.quantization,
            size=model.size,
            format=model.format,
            source=model.source,
            family=model.family,
            version=model.version,
            description=model.description,
            tags=json.loads(model.tags_json or "[]"),
            metadata=json.loads(model.metadata_json or "{}"),
        )

    def get_model_chat_params(self, model_id: str) -> Dict[str, Any]:
        """获取模型的聊天参数配置"""
        with db_session() as db:
            config = db.query(ModelConfig).filter(ModelConfig.model_id == model_id).first()
            if config and config.chat_params_json:
                return json.loads(config.chat_params_json)
        return {}

    def save_model_chat_params(self, model_id: str, params: Dict[str, Any]) -> None:
        """保存模型的聊天参数配置"""
        params_json = json.dumps(params)
        with db_session() as db:
            stmt = insert(ModelConfig).values(
                model_id=model_id,
                chat_params_json=params_json,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["model_id"],
                set_={
                    "chat_params_json": stmt.excluded.chat_params_json,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            db.execute(stmt)

    def delete_model(self, model_id: str) -> bool:
        """从数据库删除模型（含 model_configs，通过 CASCADE 自动删除）"""
        with db_session() as db:
            model = db.query(Model).filter(Model.id == model_id).first()
            if model:
                db.delete(model)
                return True
        return False


# 单例实例
_registry: Optional[ModelRegistry] = None


def get_model_registry() -> ModelRegistry:
    """获取模型注册中心单例"""
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry
