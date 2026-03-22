from typing import Optional, List, Union
import time
from core.models.descriptor import ModelDescriptor
from core.models.registry import get_model_registry
from config.settings import settings
from log import logger

# Provider endpoint configurations
PROVIDER_ENDPOINTS = {
    'ollama': 'http://localhost:11434',
    'lmstudio': 'http://localhost:1234',
}

# Cache for provider availability (refresh every 30 seconds)
_provider_cache: dict = {}
_cache_ttl = 30

def invalidate_provider_cache():
    """Invalidate the provider availability cache."""
    global _provider_cache
    _provider_cache = {}

def _check_provider_available(provider: str, base_url: str = None) -> bool:
    """
    Check if a provider endpoint is available.

    Important:
    - This method is called on the chat request critical path.
    - To avoid request-thread blocking, we only read cached availability and
      never perform synchronous network probing here.
    - If cache is missing/stale, we optimistically assume available.
    """
    now = time.time()
    
    # Check cache
    cache_key = f"{provider}:{base_url or PROVIDER_ENDPOINTS.get(provider, '')}"
    if cache_key in _provider_cache:
        cached_time, cached_result = _provider_cache[cache_key]
        if now - cached_time < _cache_ttl:
            return cached_result
    
    # For non-network providers, assume available.
    if provider not in ('ollama', 'lmstudio'):
        return True

    # For network-like local providers, avoid sync probing in request path.
    # When no fresh cache is present, fallback to optimistic True.
    return True

class ModelSelector:
    """
    模型选择器
    根据请求要求或系统策略选择最佳模型
    
    支持智能 Auto 模式：
    - 自动检测消息中是否包含图像
    - 有图像时自动切换到 VLM (Vision Language Model)
    - 无图像时使用普通 LLM
    - 优先选择本地模型，其次云端模型
    - 自动排除不可用 provider 的模型
    """
    
    def __init__(self):
        self.registry = get_model_registry()

    def _has_image_content(self, messages: Optional[List[dict]]) -> bool:
        """
        检测消息中是否包含图像内容
        
        支持两种格式:
        1. OpenAI 格式: content 为 List[dict], 其中包含 type='image_url'
        2. 简单检测: 检查是否有 image_url 字段
        """
        if not messages:
            return False
        
        logger.debug(f"[ModelSelector] Checking {len(messages)} messages for image content")
        
        for i, msg in enumerate(messages):
            content = msg.get('content')
            if not content:
                continue
            
            # 如果 content 是列表（多模态格式）
            if isinstance(content, list):
                logger.debug(f"[ModelSelector] Message {i}: content is list with {len(content)} items")
                for item in content:
                    if isinstance(item, dict) and item.get('type') == 'image_url':
                        logger.info(f"[ModelSelector] Found image_url in message {i}")
                        return True
            
            # 兼容：检查是否有 image_url 字段直接在消息上
            if msg.get('image_url'):
                logger.info(f"[ModelSelector] Found image_url field on message {i}")
                return True
        
        logger.debug("[ModelSelector] No image content found in messages")
        return False

    def _is_local_model(self, model: ModelDescriptor) -> bool:
        """
        判断模型是否为本地模型
        
        检查规则:
        1. 模型 ID 包含 ':cloud' 后缀 -> 云端模型
        2. source 字段明确指示云端 -> 云端模型
        3. provider 为 local/llama.cpp -> 本地模型
        4. provider 为 ollama/lmstudio 且无云端标记 -> 本地模型
        """
        # 1. ID 包含 :cloud 后缀 -> 云端模型
        model_id_lower = model.id.lower()
        if ':cloud' in model_id_lower or model_id_lower.endswith(':cloud'):
            return False
        
        # 2. source 字段明确指示云端
        source = (model.source or '').lower()
        if source in ('cloud', 'api', 'remote', 'huggingface', 'cloud api'):
            return False
        
        # 3. metadata 中标记为云端
        if model.metadata.get('cloud', False) or model.metadata.get('remote', False):
            return False
        
        # 4. provider 判断
        if model.provider in ('local', 'llama.cpp'):
            return True
        
        # 5. ollama/lmstudio 默认为本地（除非上述条件已排除）
        if model.provider in ('ollama', 'lmstudio'):
            return True
        
        # 6. 其他情况（如 openai, anthropic, gemini）视为云端
        return False

    def _is_vlm_model(self, model: ModelDescriptor) -> bool:
        """Check if model is a Vision Language Model."""
        # Check model_type
        if model.model_type == 'vlm':
            return True
        # Check capabilities
        if 'vision' in model.capabilities:
            return True
        # Check ID/name for common VLM patterns
        id_lower = model.id.lower()
        name_lower = (model.name or '').lower()
        vlm_patterns = ['vlm', 'vision', 'llava', 'internvl', 'qwen-vl', 'qwen2-vl', 'qwen3-vl', 'claude-3', 'gpt-4-vision', 'gpt-4o']
        for pattern in vlm_patterns:
            if pattern in id_lower or pattern in name_lower:
                return True
        return False

    def _get_model_quality_score(self, model: ModelDescriptor) -> int:
        """
        Estimate model quality based on size/family.
        Larger models and newer generations score higher.
        """
        score = 0
        id_lower = model.id.lower()
        name_lower = (model.name or '').lower()
        
        # Model size estimation from ID/name
        size_score = 0
        if '70b' in id_lower or '72b' in id_lower or '27b' in id_lower:
            size_score = 40  # Very large, high quality
        elif '34b' in id_lower or '32b' in id_lower or '30b' in id_lower:
            size_score = 30
        elif '14b' in id_lower or '13b' in id_lower or '9b' in id_lower or '8b' in id_lower:
            size_score = 20
        elif '7b' in id_lower or '6b' in id_lower:
            size_score = 10
        elif '2b' in id_lower or '3b' in id_lower or '1.5b' in id_lower:
            size_score = 5
        
        score += size_score
        
        # Model family/generation bonus
        family_score = 0
        # High-quality families
        if 'claude' in id_lower or 'opus' in id_lower or 'gpt-4' in id_lower:
            family_score = 30
        elif 'qwen3.5' in id_lower or 'qwen3.5' in name_lower:
            family_score = 25  # Qwen 3.5 is very capable
        elif 'qwen3' in id_lower and 'qwen3.5' not in id_lower:
            family_score = 20
        elif 'llama-3' in id_lower or 'llama3' in id_lower:
            family_score = 20
        elif 'qwen2' in id_lower:
            family_score = 15
        elif 'llava' in id_lower:
            family_score = 15  # Good VLM
        elif 'internvl' in id_lower:
            family_score = 18  # InternVL is quite capable
        
        score += family_score
        
        return score

    def _score_model(self, model: ModelDescriptor, prefer_vision: bool = False) -> int:
        """
        为模型打分，用于排序选择
        分数越高越优先
        
        评分标准:
        - 基础分: 100
        - 模型质量: +5~70 (基于大小和家族)
        - 能力匹配: +50 (vision 能力且需要时)
        - 本地模型: +30 (优先本地推理)
        - 上下文长度: +5~10 (更大的上下文)
        - 云端模型: 0 (作为备选)
        """
        score = 100
        
        # 模型质量评分（基于大小和家族）
        quality_score = self._get_model_quality_score(model)
        score += quality_score
        
        # 能力匹配（使用改进的 VLM 检测）
        is_vlm = self._is_vlm_model(model)
        if prefer_vision and is_vlm:
            score += 50
        elif prefer_vision and not is_vlm:
            # 需要视觉能力但没有，大幅降分
            score -= 80
        
        # 本地模型优先（使用更精确的判断）
        if self._is_local_model(model):
            score += 30
        
        # 上下文长度加分
        ctx_len = model.context_length or 4096
        if ctx_len >= 8192:
            score += 10
        elif ctx_len >= 4096:
            score += 5
        
        return score

    def resolve(
        self, 
        model_id: Optional[str] = None, 
        model_require: Optional[str] = None,
        messages: Optional[List[dict]] = None
    ) -> ModelDescriptor:
        """
        解析模型请求
        
        优先级:
        1. 精确 model_id (如 'ollama:llama3')
        2. 基于能力的 model_require (如 'vision', 'fast')
        3. 智能 Auto 模式 (根据消息内容自动选择)
        4. 默认配置
        
        Args:
            model_id: 指定的模型 ID，'auto' 表示自动选择
            model_require: 能力要求，如 'vision'
            messages: 消息列表，用于智能检测是否需要视觉模型
        """
        # 1. 精确匹配 (非 'auto')
        if model_id and model_id != "auto":
            # 处理特殊别名
            if model_id == "ollama":
                return self._get_default_for_provider("ollama")
            if model_id == "lmstudio":
                return self._get_default_for_provider("lmstudio")
                
            model = self.registry.get_model(model_id)
            if model:
                return model
            
            # 如果没找到，尝试按 provider_model_id 模糊匹配
            all_models = self.registry.list_models()
            for m in all_models:
                if m.provider_model_id == model_id:
                    return m

        # 2. 能力匹配
        if model_require:
            models = self.registry.list_models()
            # 简单实现：检查 capabilities 或 tags 是否包含关键词
            for m in models:
                if model_require in m.capabilities or model_require in m.tags:
                    return m
        
        # 3. 智能 Auto 模式
        # 检测是否需要视觉能力
        needs_vision = self._has_image_content(messages)
        
        if needs_vision:
            logger.info("[ModelSelector] Auto mode: detected image content, preferring VLM")
        
        # 获取所有可用模型并评分
        all_models = self.registry.list_models()
        
        if not all_models:
            raise ValueError("No models available in registry. Please ensure providers are running.")
        
        # 过滤出合适的模型类型
        if needs_vision:
            # 必须是 VLM（使用改进的检测方法）
            candidate_models = [m for m in all_models if self._is_vlm_model(m)]
            if not candidate_models:
                logger.warning("[ModelSelector] No VLM available, falling back to regular LLM")
                candidate_models = all_models
        else:
            # 普通对话，排除纯视觉模型（如果有的话）
            candidate_models = [m for m in all_models if m.model_type in ('llm', 'vlm') or 'chat' in m.capabilities]
            if not candidate_models:
                candidate_models = all_models
        
        # 过滤掉不可用 provider 的模型
        available_providers = set()
        unavailable_providers = set()
        for m in candidate_models:
            if m.provider in available_providers or m.provider in unavailable_providers:
                continue
            if _check_provider_available(m.provider, m.base_url):
                available_providers.add(m.provider)
            else:
                unavailable_providers.add(m.provider)
        
        # 只保留可用 provider 的模型
        filtered_models = [m for m in candidate_models if m.provider in available_providers or m.provider not in ('ollama', 'lmstudio')]
        
        if unavailable_providers:
            logger.info(f"[ModelSelector] Unavailable providers detected: {unavailable_providers}, excluding their models")
        
        if not filtered_models:
            # 如果所有模型都不可用，回退到原始列表（可能是云端模型）
            logger.warning("[ModelSelector] No models from available providers, using all candidates")
            filtered_models = candidate_models
        
        candidate_models = filtered_models

        # 3.1 可配置的强本地优先：存在本地候选时仅在本地模型中选择
        if bool(getattr(settings, "model_selector_auto_local_first_strict", True)):
            local_candidates = [m for m in candidate_models if self._is_local_model(m)]
            if local_candidates:
                logger.info(
                    "[ModelSelector] Strict local-first enabled: %d/%d local candidates kept",
                    len(local_candidates),
                    len(candidate_models),
                )
                candidate_models = local_candidates
            else:
                logger.warning(
                    "[ModelSelector] Strict local-first enabled but no local candidates found; falling back to non-local candidates"
                )

        # 按评分排序
        scored_models = [(m, self._score_model(m, prefer_vision=needs_vision)) for m in candidate_models]
        scored_models.sort(key=lambda x: x[1], reverse=True)
        
        # Debug: log top 5 candidates
        logger.debug(f"[ModelSelector] Top 5 candidates (needs_vision={needs_vision}):")
        for m, score in scored_models[:5]:
            is_local = self._is_local_model(m)
            is_vlm = self._is_vlm_model(m)
            quality = self._get_model_quality_score(m)
            logger.debug(f"  - {m.id}: score={score}, quality={quality}, is_local={is_local}, is_vlm={is_vlm}, provider={m.provider}")
        
        best_model, best_score = scored_models[0]
        
        logger.info(
            f"[ModelSelector] Auto selected: {best_model.id} (score={best_score}, "
            f"provider={best_model.provider}, is_local={self._is_local_model(best_model)}, is_vlm={self._is_vlm_model(best_model)}, needs_vision={needs_vision})"
        )
        
        return best_model

    def _get_default_for_provider(self, provider: str) -> ModelDescriptor:
        """Get the default model for a provider, checking availability first."""
        # Check provider availability
        if not _check_provider_available(provider):
            logger.warning(f"[ModelSelector] Provider {provider} is not available, but was explicitly requested")
        
        models = self.registry.list_models(provider=provider)
        if not models:
            raise ValueError(f"No models found for provider: {provider}")
        return models[0]

# 单例
_selector = None

def get_model_selector() -> ModelSelector:
    global _selector
    if _selector is None:
        _selector = ModelSelector()
    return _selector
