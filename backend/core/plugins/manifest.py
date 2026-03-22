from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional

class PluginManifest(BaseModel):
    """
    Plugin Manifest 定义
    与 plugin.json 结构对应
    """
    name: str = Field(..., description="插件名称")
    version: str = Field(..., description="版本号")
    description: str = Field(..., description="功能描述")
    entry: str = Field(..., description="入口类路径 (e.g. core.plugins.builtin.rag.plugin:RAGPlugin)")
    type: str = Field(default="capability", description="插件类型: system/model/capability")
    stage: str = Field(default="pre", description="执行阶段: pre/post/tool/router")
    supported_modes: List[str] = Field(default_factory=list, description="支持的模式 (chat/agent/task)")
    input_schema: Dict[str, Any] = Field(default_factory=dict, description="输入参数 Schema (JSON Schema)")
    output_schema: Dict[str, Any] = Field(default_factory=dict, description="输出结果 Schema (JSON Schema)")
    permissions: Optional[List[str]] = Field(default=None, description="所需权限列表")
    config_schema: Optional[Dict[str, Any]] = Field(default=None, description="配置项 Schema")
