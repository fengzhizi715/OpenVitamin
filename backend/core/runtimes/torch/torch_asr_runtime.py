"""
TorchASRRuntime: 基于 PyTorch + faster-whisper / Whisper 的 ASR 运行时

- 支持 faster-whisper（优先）和原生 Whisper（备选）
- 处理音频文件（wav/mp3/m4a）和原始 PCM buffer（16kHz, mono）
- 返回标准化的转录结果（text, language, segments）
"""

import asyncio
import json
import platform
from pathlib import Path
from typing import Union, Optional, Dict, Any

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

try:
    import zhconv
    ZHCONV_AVAILABLE = True
except ImportError:
    ZHCONV_AVAILABLE = False

try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False
    try:
        import whisper
        WHISPER_AVAILABLE = True
    except ImportError:
        WHISPER_AVAILABLE = False


class TorchASRRuntime:
    """
    Torch ASR Runtime
    
    基于 faster-whisper（优先）或原生 Whisper 的语音识别运行时。
    从 model.json 读取配置，支持多种设备（CPU/CUDA/MPS）。
    """

    def __init__(self, model_dir: Union[str, Path], model_config: Optional[Dict[str, Any]] = None):
        """
        初始化 ASR Runtime
        
        Args:
            model_dir: 模型目录路径（包含 model.json）
            model_config: 可选的模型配置字典（如果不提供，会从 model_dir/model.json 读取）
        """
        self._model_dir = Path(model_dir)
        self._config = model_config or self._load_config()
        self._model = None
        self._lock = asyncio.Lock()
        self._use_faster_whisper = False  # 将在 _load_model 中设置
        
        # 检查依赖
        if not FASTER_WHISPER_AVAILABLE and not WHISPER_AVAILABLE:
            raise ImportError(
                "Neither faster-whisper nor openai-whisper is installed. "
                "Please install one of them:\n"
                "  pip install faster-whisper  # 推荐，更快\n"
                "  # 或\n"
                "  pip install openai-whisper"
            )

    def _load_config(self) -> Dict[str, Any]:
        """从 model.json 加载配置"""
        config_path = self._model_dir / "model.json"
        if not config_path.exists():
            raise FileNotFoundError(f"model.json not found in {self._model_dir}")
        
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _get_device(self) -> str:
        """
        根据配置和系统环境确定设备
        
        优先级：
        1. metadata.device（显式配置）
        2. 自动检测（CUDA > MPS > CPU）
        """
        device = self._config.get("metadata", {}).get("device", "auto")
        
        if device == "auto":
            # 自动检测
            if platform.system() == "Darwin":  # macOS
                return "mps"
            # 检查 CUDA
            try:
                import torch
                if torch.cuda.is_available():
                    return "cuda"
            except ImportError:
                pass
            return "cpu"
        
        return device.lower()

    def _get_model_path(self) -> str:
        """
        获取模型路径或标识符
        
        path 可能是：
        - "." 或空：使用 model_dir 本身
        - HuggingFace repo 名（如 "openai/whisper-small"）
        - 本地目录路径（相对于 model_dir）
        - 绝对路径
        """
        path = self._config.get("path", "")
        if not path or path == ".":
            # 使用 model_dir 本身（本地模型目录）
            return str(self._model_dir)
        
        # 如果是 HuggingFace repo 名（包含 /），直接返回
        if "/" in path and not Path(path).exists():
            return path
        
        # 尝试解析为路径
        model_path = Path(path)
        if model_path.is_absolute():
            return str(model_path)
        
        # 相对路径：相对于 model_dir
        full_path = self._model_dir / path
        if full_path.exists():
            return str(full_path)
        
        # 如果不存在，可能是 HuggingFace repo 名
        return path

    async def _load_model(self) -> None:
        """异步加载模型（线程安全）"""
        if self._model is not None:
            return
        
        async with self._lock:
            if self._model is not None:
                return
            
            device = self._get_device()
            model_path = self._get_model_path()
            
            # 优先使用 faster-whisper
            if FASTER_WHISPER_AVAILABLE:
                def _load():
                    # faster-whisper 的设备映射
                    device_map = {
                        "cuda": "cuda",
                        "mps": "cpu",  # faster-whisper 不支持 MPS，回退到 CPU
                        "cpu": "cpu",
                    }
                    fw_device = device_map.get(device, "cpu")
                    
                    # 计算类型（faster-whisper 使用 compute_type）
                    compute_type = self._config.get("metadata", {}).get("compute_type", "float16")
                    if fw_device == "cpu":
                        compute_type = "int8"  # CPU 上使用 int8 更快
                    
                    return WhisperModel(
                        model_size_or_path=model_path,
                        device=fw_device,
                        compute_type=compute_type,
                    )
                
                loop = asyncio.get_running_loop()
                self._model = await loop.run_in_executor(None, _load)
                self._use_faster_whisper = True
                
            elif WHISPER_AVAILABLE:
                def _load():
                    import whisper
                    # 原生 Whisper 的设备映射
                    device_map = {
                        "cuda": "cuda",
                        "mps": "mps",
                        "cpu": "cpu",
                    }
                    whisper_device = device_map.get(device, "cpu")
                    
                    # 如果 model_path 是目录，尝试查找模型文件
                    if Path(model_path).is_dir():
                        # 原生 Whisper 需要模型大小标识（tiny/base/small/medium/large）
                        # 这里假设 path 是模型大小或包含模型大小的路径
                        model_size = Path(model_path).name
                        if model_size in ["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"]:
                            return whisper.load_model(model_size, device=whisper_device)
                        else:
                            # 尝试从目录名推断
                            return whisper.load_model("base", device=whisper_device)
                    else:
                        # HuggingFace repo 或本地路径
                        return whisper.load_model(model_path, device=whisper_device)
                
                loop = asyncio.get_running_loop()
                self._model = await loop.run_in_executor(None, _load)
                self._use_faster_whisper = False
            else:
                raise RuntimeError("No Whisper implementation available")

    def _should_output_simplified_chinese(self, opts: Dict[str, Any], detected_lang: Optional[str]) -> bool:
        """是否将输出转为简体中文（仅当检测为中文时）"""
        metadata = self._config.get("metadata", {})
        enabled = opts.get("output_simplified_chinese", metadata.get("output_simplified_chinese", True))
        if not enabled:
            return False
        lang = (detected_lang or "").lower()
        return lang in ("zh", "zh-cn", "zh-tw", "zh-hk", "zh-hans", "zh-hant")

    def _convert_to_simplified_chinese(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """将文本和 segments 转为简体中文"""
        if not ZHCONV_AVAILABLE:
            return result
        text = result.get("text", "")
        if text:
            result["text"] = zhconv.convert(text, "zh-cn")
        for seg in result.get("segments", []):
            if seg.get("text"):
                seg["text"] = zhconv.convert(seg["text"], "zh-cn")
        return result

    def _prepare_audio(self, audio_input: Union[str, bytes]) -> Union[str, bytes]:
        """
        准备音频输入
        
        Args:
            audio_input: 音频文件路径（str）或 PCM buffer（bytes）
            
        Returns:
            处理后的音频输入（faster-whisper 和原生 Whisper 都支持文件路径和 numpy array）
        """
        if isinstance(audio_input, str):
            # 文件路径
            audio_path = Path(audio_input)
            if not audio_path.exists():
                raise FileNotFoundError(f"Audio file not found: {audio_input}")
            return str(audio_path)
        
        elif isinstance(audio_input, bytes):
            # PCM buffer（16kHz, mono）
            # 需要转换为 numpy array
            if not NUMPY_AVAILABLE:
                raise ImportError("numpy is required for PCM buffer input. Install with: pip install numpy")
            
            # 假设是 16-bit PCM（int16）
            audio_array = np.frombuffer(audio_input, dtype=np.int16).astype(np.float32) / 32768.0
            
            # 确保是单声道（mono）
            if len(audio_array.shape) > 1:
                audio_array = audio_array.mean(axis=1)
            
            return audio_array
        
        else:
            raise TypeError(f"Unsupported audio_input type: {type(audio_input)}")

    async def transcribe(
        self,
        audio_input: Union[str, bytes],
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        转录音频为文本
        
        Args:
            audio_input: 
                - str: 音频文件路径（wav/mp3/m4a）
                - bytes: PCM 音频数据（16kHz, mono, 16-bit）
            options: 可选的转录参数
                - language: 语言代码（如 "zh", "en"），"auto" 表示自动检测
                - beam_size: Beam search 大小（faster-whisper）
                - vad_filter: 是否启用 VAD 过滤（faster-whisper）
                - temperature: 采样温度（原生 Whisper）
                
        Returns:
            {
                "text": str,  # 完整转录文本
                "language": str,  # 检测到的语言代码
                "segments": [
                    {
                        "start": float,  # 开始时间（秒）
                        "end": float,  # 结束时间（秒）
                        "text": str  # 该段文本
                    }
                ]
            }
        """
        # 确保模型已加载
        await self._load_model()
        
        # 合并选项
        opts = options or {}
        metadata = self._config.get("metadata", {})
        language = opts.get("language", metadata.get("language", "auto"))
        if language == "auto":
            language = None  # None 表示自动检测
        
        # 准备音频
        prepared_audio = self._prepare_audio(audio_input)
        
        # 执行转录
        if self._use_faster_whisper:
            result = await self._transcribe_faster_whisper(prepared_audio, language, opts)
        else:
            result = await self._transcribe_whisper(prepared_audio, language, opts)

        # 可选：输出统一为简体中文
        if self._should_output_simplified_chinese(opts, result.get("language")):
            result = self._convert_to_simplified_chinese(result)
        return result

    async def _transcribe_faster_whisper(
        self,
        audio: Union[str, Any],  # str 或 np.ndarray
        language: Optional[str],
        options: Dict[str, Any]
    ) -> Dict[str, Any]:
        """使用 faster-whisper 转录"""
        
        beam_size = options.get("beam_size", 5)
        vad_filter = options.get("vad_filter", False)
        
        def _run():
            segments, info = self._model.transcribe(
                audio,
                language=language,
                beam_size=beam_size,
                vad_filter=vad_filter,
            )
            
            # 收集所有 segments
            segment_list = []
            full_text_parts = []
            
            for seg in segments:
                segment_list.append({
                    "start": float(seg.start),
                    "end": float(seg.end),
                    "text": seg.text.strip(),
                })
                full_text_parts.append(seg.text.strip())
            
            # faster-whisper 的 info 对象包含 language 属性
            detected_language = getattr(info, "language", None) or language or "unknown"
            # 根据语言选择拼接方式：中文/日文等不用空格，英文等用空格
            sep = "" if (detected_language or "").lower() in ("zh", "ja", "ko", "th", "vi") else " "
            full_text = sep.join(full_text_parts)
            
            return {
                "text": full_text,
                "language": detected_language,
                "segments": segment_list,
            }
        
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _run)

    async def _transcribe_whisper(
        self,
        audio: Union[str, Any],  # str 或 np.ndarray
        language: Optional[str],
        options: Dict[str, Any]
    ) -> Dict[str, Any]:
        """使用原生 Whisper 转录"""
        
        temperature = options.get("temperature", 0.0)
        
        def _run():
            result = self._model.transcribe(
                audio,
                language=language,
                temperature=temperature,
            )
            
            # 原生 Whisper 返回格式
            detected_language = result.get("language", language or "unknown")
            full_text = result.get("text", "").strip()
            # 若 result 无 text 但有 segments，按语言拼接
            if not full_text and result.get("segments"):
                seg_texts = [s.get("text", "").strip() for s in result["segments"]]
                sep = "" if (detected_language or "").lower() in ("zh", "ja", "ko", "th", "vi") else " "
                full_text = sep.join(seg_texts)
            
            segments = []
            for seg in result.get("segments", []):
                segments.append({
                    "start": seg.get("start", 0.0),
                    "end": seg.get("end", 0.0),
                    "text": seg.get("text", "").strip(),
                })
            
            return {
                "text": full_text,
                "language": detected_language,
                "segments": segments,
            }
        
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _run)

    async def unload(self) -> None:
        """卸载模型，释放资源"""
        async with self._lock:
            if self._model is not None:
                # faster-whisper 和原生 Whisper 的模型对象会在 GC 时自动释放
                # 这里可以显式清理
                self._model = None

    @property
    def is_loaded(self) -> bool:
        """检查模型是否已加载"""
        return self._model is not None

    @property
    def model_info(self) -> Dict[str, Any]:
        """获取模型信息"""
        metadata = self._config.get("metadata", {})
        return {
            "runtime": "torch",
            "modality": "asr",
            "model_dir": str(self._model_dir),
            "model_path": self._get_model_path(),
            "device": self._get_device(),
            "implementation": "faster-whisper" if FASTER_WHISPER_AVAILABLE else "whisper",
            "sample_rate": metadata.get("sample_rate", 16000),
        }

    def health(self) -> Dict[str, Any]:
        """健康检查"""
        if self._model:
            return {"status": "loaded", "implementation": "faster-whisper" if self._use_faster_whisper else "whisper"}
        return {"status": "not_loaded"}
