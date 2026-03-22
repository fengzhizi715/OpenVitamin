"""
OpenAI 官方 API 模型代理实现
"""
from core.agents.openai_compatible_agent import OpenAICompatibleAgent


class OpenAIAgent(OpenAICompatibleAgent):
    """
    OpenAI 官方 API 适配器
    """
    
    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1"):
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            backend_name="openai"
        )

    def model_info(self) -> dict:
        info = super().model_info()
        info.update({
            "description": "OpenAI Cloud API",
            "device": "cloud"
        })
        return info
