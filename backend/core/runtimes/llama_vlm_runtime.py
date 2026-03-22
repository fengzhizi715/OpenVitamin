"""
LlamaCppVLMRuntime: llama.cpp 后端的具体 VLM Runtime 实现

基于 llama-cpp-python 的 Qwen3-VL 多模态推理实现。
严格遵循 VLMRuntime 抽象接口，不暴露 vision token 或内部细节。
"""

import asyncio
from typing import Union, Optional, Dict, Any
from pathlib import Path

try:
    from PIL import Image
    import PIL
except ImportError:
    PIL = None
    Image = None

try:
    import llama_cpp
except ImportError:
    llama_cpp = None

from .vlm_runtime import VLMRuntime


class LlamaCppVLMRuntime(VLMRuntime):
    """
    基于 llama.cpp 的 VLM Runtime 实现
    
    关键设计原则：
    1. 严格遵守 VLMRuntime 抽象接口
    2. 不复用 LLMRuntime 任何代码
    3. 完全依赖 llama.cpp 内部多模态处理
    4. 不在上层处理 vision token 或图像编码
    """
    
    def __init__(
        self,
        model_path: Union[str, Path],
        mmproj_path: Optional[Union[str, Path]] = None,
        vlm_family: Optional[str] = None,
        n_ctx: int = 8192,
        n_gpu_layers: int = 0,
        verbose: bool = False
    ):
        """
        构造函数 - 配置 llama.cpp 参数
        
        Args:
            model_path: GGUF 模型文件路径
            n_ctx: 上下文长度
            n_gpu_layers: GPU 加速层数 (0=CPU only)
            verbose: 是否输出详细日志
            
        设计理由：
        - 接收具体 llama.cpp 参数而非通用 kwargs
        - model_path 在构造时确定，符合初始化模式
        - 其他参数有合理默认值，保持接口简洁
        """
        if llama_cpp is None:
            raise RuntimeError("llama-cpp-python not installed")
        
        self._model_path = Path(model_path) if isinstance(model_path, str) else model_path
        self._mmproj_path = Path(mmproj_path) if isinstance(mmproj_path, str) else mmproj_path
        self._vlm_family = vlm_family
        self._n_ctx = n_ctx
        self._n_gpu_layers = n_gpu_layers
        self._verbose = verbose
        
        # 延迟初始化，避免构造函数阻塞
        self._model: Optional[llama_cpp.Llama] = None
        self._chat_handler: Optional[object] = None
        self._lock = asyncio.Lock()
    
    async def initialize(self, model_path: Union[str, Path] = None, **kwargs) -> None:
        """
        异步初始化 llama.cpp 模型
        
        Args:
            model_path: 可选的模型路径覆盖（主要用于接口兼容）
            **kwargs: 忽略的额外参数（保持接口一致性）
            
        设计理由：
        - 使用实例变量存储的路径，支持重新初始化
        - 异步包装同步的 llama_cpp.Llama 构造
        - 线程安全的初始化检查
        """
        # 如果已在初始化或已加载，直接返回
        if self._model is not None:
            return
            
        async with self._lock:
            # 双重检查锁定模式
            if self._model is not None:
                return
                
            # 使用构造函数参数或覆盖参数
            actual_path = model_path if model_path is not None else self._model_path

            # best-effort: resolve mmproj/clip model path for VLM chat handler
            actual_mmproj_path = kwargs.get("mmproj_path") or kwargs.get("clip_model_path") or self._mmproj_path
            actual_vlm_family = kwargs.get("vlm_family") or self._vlm_family

            def _normalize_family(x: Optional[str]) -> str:
                return (x or "").strip().lower()

            family = _normalize_family(actual_vlm_family)
            path_lower = str(actual_path).lower()
            wants_llava = ("llava" in family) or ("llava" in path_lower)
            wants_qwen25_vl = ("qwen" in family and "vl" in family) or ("qwen" in path_lower and "vl" in path_lower)

            # If llava but mmproj not provided, try auto-discovery in model directory.
            if wants_llava and not actual_mmproj_path:
                model_dir = Path(actual_path).parent
                mmproj_files = list(model_dir.glob("*-mmproj*.gguf")) or list(model_dir.glob("mmproj-*.gguf"))
                if mmproj_files:
                    actual_mmproj_path = mmproj_files[0]
            
            # 在线程池中执行 CPU 密集型的模型加载
            loop = asyncio.get_running_loop()
            self._model = await loop.run_in_executor(
                None,
                lambda: llama_cpp.Llama(
                    model_path=str(actual_path),
                    n_ctx=self._n_ctx,
                    n_gpu_layers=self._n_gpu_layers,
                    verbose=self._verbose,
                    # VLM chat handlers (e.g., LLaVA) may require logits_all=True
                    logits_all=True,
                    embedding=False,   # VLM 不需要 embedding 输出
                    chat_handler=self._build_chat_handler(
                        mmproj_path=actual_mmproj_path,
                        wants_llava=wants_llava,
                        wants_qwen25_vl=wants_qwen25_vl,
                    ),
                )
            )
    
    def _build_chat_handler(
        self,
        *,
        mmproj_path: Optional[Union[str, Path]],
        wants_llava: bool,
        wants_qwen25_vl: bool,
    ) -> Optional[object]:
        """
        Build llama-cpp-python chat handler for VLMs.

        Notes:
        - For LLaVA v1.5, llama_cpp.llama_chat_format.Llava15ChatHandler is required to actually
          consume image inputs (clip/mmproj).
        - This stays best-effort: if handler import fails or mmproj missing, we fall back to None.
        """
        # Reset any previous handler reference (initialize should only run once, but keep safe)
        self._chat_handler = None

        if llama_cpp is None:
            return None

        if not mmproj_path:
            return None

        try:
            from llama_cpp.llama_chat_format import Llava15ChatHandler, Qwen25VLChatHandler
        except Exception:
            return None

        try:
            if wants_llava:
                self._chat_handler = Llava15ChatHandler(clip_model_path=str(mmproj_path), verbose=self._verbose)
                return self._chat_handler
            if wants_qwen25_vl:
                self._chat_handler = Qwen25VLChatHandler(clip_model_path=str(mmproj_path), verbose=self._verbose)
                return self._chat_handler
        except Exception:
            self._chat_handler = None
            return None

        return None

    async def infer(
        self,
        image: Union[Image.Image, bytes],
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        """
        执行多模态推理
        
        Args:
            image: PIL 图像对象或图像字节数据
            prompt: 文本提示词
            temperature: 采样温度
            max_tokens: 最大生成 token 数
            **kwargs: 其他 llama.cpp 参数（如 top_p, frequency_penalty 等）
            
        Returns:
            str: 模型生成的文本结果
            
        设计理由：
        1. 直接使用 llama.cpp 的多模态聊天接口
        2. 不进行图像预处理，完全依赖 llama.cpp 内部 vision encoder
        3. 将图像和文本组合成标准聊天格式
        4. 只返回最终文本，不暴露中间表示
        """
        if self._model is None:
            raise RuntimeError("Model not initialized. Call initialize() first.")
        
        system_prompt = (kwargs.get("system_prompt") or "").strip()

        # 准备多模态输入
        # llama.cpp 期望的格式：[{"role": "user", "content": [...]}]
        # 其中 content 可以包含文本和图像元素
        chat_messages = []
        if system_prompt:
            chat_messages.append({"role": "system", "content": system_prompt})

        chat_messages.append(
            {
                "role": "user",
                "content": [
                    # Many VLM chat formats expect the image token before the prompt text.
                    {"type": "image_url", "image_url": {"url": self._encode_image(image)}},
                    {"type": "text", "text": prompt},
                ],
            }
        )
        
        # 构建推理参数
        generation_kwargs = {
            "messages": chat_messages,
            "max_tokens": max_tokens if (max_tokens is not None and max_tokens > 0) else 2048,
            "temperature": temperature or 0.7,  # 合理默认值
        }
        
        # 添加其他可选参数
        if "top_p" in kwargs:
            generation_kwargs["top_p"] = kwargs["top_p"]
        if "frequency_penalty" in kwargs:
            generation_kwargs["frequency_penalty"] = kwargs["frequency_penalty"]
        if "presence_penalty" in kwargs:
            generation_kwargs["presence_penalty"] = kwargs["presence_penalty"]
        
        # 执行推理（同步调用）
        # 注意：create_chat_completion 是同步方法，必须放到线程池，避免阻塞事件循环
        response = await asyncio.to_thread(self._model.create_chat_completion, **generation_kwargs)
        
        # 提取并返回文本结果
        # response 格式：{"choices": [{"message": {"content": "..."}}]}
        return response["choices"][0]["message"]["content"]
    
    async def unload(self) -> None:
        """
        卸载模型资源
        
        设计理由：
        - 显式释放 llama.cpp 模型占用的内存/GPU资源
        - 异步包装同步操作以保持接口一致性
        - 清理所有内部状态
        """
        async with self._lock:
            if self._model is not None:
                try:
                    # Best-effort: release native resources if exposed
                    if hasattr(self._model, "reset"):
                        self._model.reset()
                    elif hasattr(self._model, "close"):
                        self._model.close()
                except Exception:
                    pass
                finally:
                    self._model = None
                    # Best-effort: close VLM chat handler resources (mtmd/clip context)
                    try:
                        if self._chat_handler is not None:
                            exit_stack = getattr(self._chat_handler, "_exit_stack", None)
                            close_fn = getattr(exit_stack, "close", None)
                            if callable(close_fn):
                                close_fn()
                    except Exception:
                        pass
                    finally:
                        self._chat_handler = None
                    import gc
                    gc.collect()
    
    @property
    def is_loaded(self) -> bool:
        """
        检查模型是否已加载
        
        Returns:
            bool: 模型加载状态
        """
        return self._model is not None
    
    @property
    def model_info(self) -> Dict[str, Any]:
        """
        获取模型元信息
        
        Returns:
            Dict: 包含模型基本信息的字典（高层抽象，不暴露内部表示细节）
        """
        info = {
            "runtime": "llama.cpp",
            "modality": "vlm",  # 明确这是多模态 VLM 而非纯文本 LLM
            "model_path": str(self._model_path),
            "max_context_tokens": self._n_ctx,
        }
        
        # 注意：这里刻意不暴露 vocab_size / embedding_length 等内部几何信息
        # 如果未来需要做诊断，可以通过单独的调试接口获取，而不是放在通用 Runtime 接口中
        return info
    
    def _encode_image(self, image: Union[Image.Image, bytes]) -> str:
        """
        将图像编码为 llama.cpp 可接受的格式
        
        Args:
            image: PIL 图像或字节数据
            
        Returns:
            str: Base64 编码的图像 URL
            
        设计理由：
        1. 不进行图像预处理（如 resize、normalize）
        2. 完全依赖 llama.cpp 内部的 vision encoder
        3. 只做必要的格式转换以满足接口要求
        4. 保持图像原始信息不丢失
        """
        import base64
        from io import BytesIO
        
        def _sniff_mime(b: bytes) -> str:
            if b.startswith(b"\x89PNG\r\n\x1a\n"):
                return "image/png"
            if b.startswith(b"\xff\xd8\xff"):
                return "image/jpeg"
            if b.startswith(b"RIFF") and b[8:12] == b"WEBP":
                return "image/webp"
            if b[:6] in (b"GIF87a", b"GIF89a"):
                return "image/gif"
            return "application/octet-stream"

        mime = "application/octet-stream"

        # 如果已经是字节数据，直接编码（黑盒：不改内容）
        if isinstance(image, bytes):
            image_bytes = image
            mime = _sniff_mime(image_bytes)
        # 如果是 PIL 图像，尽量无损编码为 PNG（避免 JPEG 有损压缩改变输入语义）
        elif PIL and isinstance(image, PIL.Image.Image):
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            image_bytes = buffer.getvalue()
            mime = "image/png"
        else:
            raise ValueError("Image must be PIL.Image or bytes")
        
        # 转换为 base64 data URL
        encoded = base64.b64encode(image_bytes).decode('utf-8')
        return f"data:{mime};base64,{encoded}"


# 使用示例（仅供说明）：
"""
async def main():
    # 创建运行时实例
    runtime = LlamaCppVLMRuntime(
        model_path="/path/to/qwen3-vl.gguf",
        n_ctx=8192,
        n_gpu_layers=33  # 根据 GPU 内存调整
    )
    
    # 初始化模型
    await runtime.initialize()
    
    # 准备输入
    from PIL import Image
    image = Image.open("input.jpg")
    prompt = "Describe this image in detail."
    
    # 执行推理
    result = await runtime.infer(
        image=image,
        prompt=prompt,
        temperature=0.7,
        max_tokens=512
    )
    
    print(result)
    
    # 清理资源
    await runtime.unload()

if __name__ == "__main__":
    asyncio.run(main())
"""