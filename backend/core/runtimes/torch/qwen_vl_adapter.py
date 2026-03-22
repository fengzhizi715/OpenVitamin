"""
QwenVLAdapter: Qwen2-VL / Qwen3-VL 模型适配器

使用 Qwen-VL 的 processor，支持 vision encoder + LLM 解耦结构。
处理多 image + 多轮对话。
"""

from pathlib import Path
from typing import Dict, Any, List, Optional, Union
import base64
from io import BytesIO

try:
    from PIL import Image
except ImportError:
    Image = None

from .model_adapter import ModelAdapter
from .internvl_adapter import _load_image, _extract_images_from_messages


class QwenVLAdapter(ModelAdapter):
    """
    Qwen-VL 系列适配器（Qwen2-VL、Qwen3-VL）

    使用 Qwen2VLForConditionalGeneration + Qwen2VLProcessor。
    支持多图、多轮对话。
    """

    def __init__(self):
        self._model = None
        self._processor = None
        self._model_name: Optional[str] = None
        self._device: str = "auto"
        self._torch_dtype = None
        self._max_image_side: int = 1536
        self._max_image_pixels: int = 1_572_864  # ~1.5MP

    def load(self, model_dir: Path, options: Dict[str, Any]) -> None:
        import json
        import torch
        from transformers import AutoModel, AutoProcessor
        
        model_name = options.get("model_name") or str(model_dir)
        architecture = (options.get("architecture") or "").lower().replace("_", "-")
        
        # 先读 config.json 确定真实 model_type（qwen3_5 与 qwen3_vl 配置不兼容）
        config_model_type = ""
        try:
            config_path = Path(model_dir) / "config.json"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    config_model_type = (json.load(f).get("model_type") or "").lower()
        except Exception:
            pass
        
        # Qwen 3.5：model_type 为 qwen3_5，必须用 AutoModel 按 config 加载 Qwen3_5ForConditionalGeneration
        use_qwen35 = config_model_type == "qwen3_5" or "qwen3.5" in architecture or "qwen3_5" in architecture
        # Qwen3-VL：model_type 为 qwen3_vl，用 Qwen3VLForConditionalGeneration
        use_qwen3_vl = config_model_type == "qwen3_vl" or ("qwen3" in architecture and "vl" in architecture and not use_qwen35)
        # 兜底：architecture 含 qwen3 但未从 config 区分时，以 config 为准
        if not use_qwen35 and not use_qwen3_vl and ("qwen3" in architecture or "qwen3" in str(model_name).lower()):
            use_qwen3_vl = config_model_type != "qwen3_5"
            use_qwen35 = config_model_type == "qwen3_5"
        
        if use_qwen35:
            # Qwen 3.5：必须用 Qwen3_5ForConditionalGeneration（带 generate/chat），AutoModel 可能加载成 Qwen3_5Model 无 generate）
            try:
                from transformers import Qwen3_5ForConditionalGeneration
                ModelClass = Qwen3_5ForConditionalGeneration
                ProcessorClass = AutoProcessor
            except ImportError as e:
                raise ImportError(
                    "Qwen 3.5 VLM 需要 Qwen3_5ForConditionalGeneration，请确保 transformers>=5.2.0。"
                    f" Original: {e}"
                )
        elif use_qwen3_vl:
            try:
                from transformers import Qwen3VLForConditionalGeneration
                ModelClass = Qwen3VLForConditionalGeneration
                ProcessorClass = AutoProcessor
            except ImportError as e:
                raise ImportError(
                    f"Qwen3-VL requires Qwen3VLForConditionalGeneration from transformers. "
                    f"Please upgrade: pip install --upgrade transformers>=4.51.0. Original: {e}"
                )
        else:
            # Qwen2-VL
            try:
                from transformers import Qwen2VLForConditionalGeneration, Qwen2VLProcessor
                ModelClass = Qwen2VLForConditionalGeneration
                ProcessorClass = Qwen2VLProcessor
            except ImportError:
                ModelClass = AutoModel
                ProcessorClass = AutoProcessor
        
        torch_dtype_str = (options.get("torch_dtype") or options.get("dtype") or "float16").lower()
        self._torch_dtype = getattr(torch, torch_dtype_str, torch.float16)
        self._device = options.get("device", "auto")
        self._model_name = model_name
        try:
            self._max_image_side = int(options.get("max_image_side", self._max_image_side) or self._max_image_side)
        except Exception:
            self._max_image_side = 1536
        try:
            self._max_image_pixels = int(options.get("max_image_pixels", self._max_image_pixels) or self._max_image_pixels)
        except Exception:
            self._max_image_pixels = 1_572_864

        self._processor = ProcessorClass.from_pretrained(model_name, trust_remote_code=True)
        
        # Qwen3-VL 需显式指定类，避免 AutoModel 选错；Qwen 3.5 必须用 AutoModel
        if use_qwen3_vl and not use_qwen35:
            try:
                from transformers import Qwen3VLForConditionalGeneration
                ModelClass = Qwen3VLForConditionalGeneration
            except ImportError:
                pass
        
        try:
            self._model = ModelClass.from_pretrained(
                model_name,
                torch_dtype=self._torch_dtype,
                trust_remote_code=True,
            )
        except (ValueError, KeyError) as e:
            err_msg = str(e).lower()
            if use_qwen35 and ("qwen3_5" in err_msg or "does not recognize" in err_msg):
                raise RuntimeError(
                    "Qwen 3.5 (qwen3_5) 需要 transformers>=5.2.0。当前版本未包含该架构。"
                    " 请执行: pip install --upgrade \"transformers>=5.2.0\" 后重试。"
                ) from e
            raise
        
        # 仅对 Qwen3-VL 做类型校验；Qwen 3.5 为 AutoModel 加载不校验
        if not use_qwen35:
            model_type_name = type(self._model).__name__
            if "Qwen3VL" in model_type_name and "ForConditionalGeneration" not in model_type_name:
                raise RuntimeError(
                    f"Loaded wrong model type: {model_type_name}. "
                    f"Qwen3-VL requires Qwen3VLForConditionalGeneration. "
                    f"Check transformers version or model files."
                )
        if self._device != "auto":
            self._model = self._model.to(self._device)
        else:
            # auto: CUDA > MPS > CPU
            if torch.cuda.is_available():
                self._model = self._model.to("cuda")
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                self._model = self._model.to("mps")
            else:
                self._model = self._model.to("cpu")
        self._model.eval()

    def _normalize_image(self, image: "Image.Image", *, max_side: Optional[int] = None, max_pixels: Optional[int] = None) -> "Image.Image":
        """
        防止超大分辨率触发视觉注意力内存爆炸（即使文件体积很小，也可能是超高分辨率图）。
        """
        if Image is None:
            return image
        img = image.convert("RGB")
        w, h = img.size
        side_cap = max(256, int(max_side or self._max_image_side))
        pixel_cap = max(262_144, int(max_pixels or self._max_image_pixels))

        scale_side = min(1.0, side_cap / float(max(w, h)))
        scale_pix = min(1.0, (pixel_cap / float(max(1, w * h))) ** 0.5)
        scale = min(scale_side, scale_pix)
        if scale >= 1.0:
            return img

        nw = max(64, int(w * scale))
        nh = max(64, int(h * scale))
        return img.resize((nw, nh), Image.Resampling.LANCZOS)

    def generate(
        self,
        messages: List[Dict[str, Any]],
        images: Optional[List[Union[str, bytes, "Image.Image"]]],
        max_tokens: int = 1024,
        temperature: float = 0.7,
        top_p: float = 1.0,
        stop: Optional[List[str]] = None,
        **kwargs
    ) -> str:
        if not self.is_loaded:
            raise RuntimeError("Model not loaded")

        pil_images, processed_messages = _extract_images_from_messages(messages, images)
        if pil_images:
            pil_images = [self._normalize_image(im) for im in pil_images]

        # 优先使用 model.chat() 方法（适用于 Qwen3-VL 等）
        if hasattr(self._model, "chat"):
            import torch
            tokenizer = getattr(self._processor, "tokenizer", self._processor)
            
            # 提取文本内容
            question_parts: List[str] = []
            system_parts: List[str] = []
            for m in processed_messages:
                role = (m.get("role") or "").lower()
                c = m.get("content")
                if isinstance(c, str):
                    text = c.strip()
                    if role == "system":
                        system_parts.append(text)
                    elif role == "user":
                        question_parts.append(text)
                elif isinstance(c, list):
                    texts = []
                    for it in c:
                        if isinstance(it, dict) and it.get("type") == "text":
                            texts.append((it.get("text") or "").strip())
                    text = "\n".join([t for t in texts if t]).strip()
                    if not text:
                        continue
                    if role == "system":
                        system_parts.append(text)
                    elif role == "user":
                        question_parts.append(text)
            
            system_prompt = "\n".join([t for t in system_parts if t]).strip()
            question = "\n".join([t for t in question_parts if t]).strip() or "Hello."
            if system_prompt:
                question = f"{system_prompt}\n\n{question}"
            
            # 处理图像
            pixel_values = None
            if pil_images:
                img_proc = (
                    getattr(self._processor, "image_processor", None)
                    or getattr(self._processor, "vision_processor", None)
                )
                if img_proc:
                    image_input = pil_images[0] if len(pil_images) == 1 else pil_images
                    out = img_proc(images=image_input, return_tensors="pt")
                    pixel_values = out.get("pixel_values") if hasattr(out, "get") else getattr(out, "pixel_values", None)
                    if pixel_values is not None:
                        try:
                            model_dtype = next(self._model.parameters()).dtype
                        except StopIteration:
                            model_dtype = self._torch_dtype
                        pixel_values = pixel_values.to(device=self._model.device, dtype=model_dtype)
            
            generation_config = {
                "max_new_tokens": int(max_tokens),
                "temperature": float(temperature),
                "top_p": float(top_p),
                "do_sample": float(temperature) > 0,
            }
            
            # 尝试不同的 chat() 签名
            with torch.no_grad():
                for args, kwargs_chat in [
                    ((tokenizer, pixel_values, question, generation_config), {}),
                    ((tokenizer, pixel_values, question, generation_config), {"history": None}),
                    ((tokenizer, pixel_values, question, generation_config), {"history": None, "return_history": False}),
                    ((tokenizer, pixel_values, question, generation_config), {"history": None, "return_history": True}),
                ]:
                    try:
                        out = self._model.chat(*args, **kwargs_chat)
                        if isinstance(out, tuple):
                            result = (out[0] or "").strip()
                        else:
                            result = (out or "").strip()
                        if stop:
                            for s in stop:
                                if s in result:
                                    result = result.split(s)[0].strip()
                        return result
                    except (TypeError, AttributeError):
                        continue
            
            # 如果所有 chat() 签名都失败，继续走下面的路径
        
        # 回退路径：使用 processor + model.generate()（适用于 Qwen2-VL）
        # Qwen2-VL 使用 processor 的 apply_chat_template 构建多模态输入
        text = self._processor.apply_chat_template(
            processed_messages,
            tokenize=False,
            add_generation_prompt=True,
        )

        # 构建 processor 输入
        if pil_images:
            if len(pil_images) == 1:
                inputs = self._processor(
                    text=[text],
                    images=[pil_images[0]],
                    padding=True,
                    return_tensors="pt",
                )
            else:
                inputs = self._processor(
                    text=[text],
                    images=[pil_images],
                    padding=True,
                    return_tensors="pt",
                )
        else:
            inputs = self._processor(
                text=[text],
                padding=True,
                return_tensors="pt",
            )

        inputs = {k: v.to(self._model.device) if hasattr(v, "to") else v for k, v in inputs.items()}

        # 确保 pixel_values 与模型 dtype 一致
        if "pixel_values" in inputs:
            try:
                model_dtype = next(self._model.parameters()).dtype
            except StopIteration:
                model_dtype = self._torch_dtype
            if inputs["pixel_values"].dtype != model_dtype:
                inputs = dict(inputs)
                inputs["pixel_values"] = inputs["pixel_values"].to(model_dtype)

        tok = getattr(self._processor, "tokenizer", self._processor)
        pad_token_id = getattr(tok, "pad_token_id", None) or getattr(tok, "eos_token_id", None)
        # 避免 transformers 内部打印 "Setting pad_token_id to eos_token_id for open-end generation"
        if getattr(tok, "pad_token_id", None) is None and pad_token_id is not None:
            tok.pad_token_id = pad_token_id
        if getattr(self._model, "generation_config", None) is not None and self._model.generation_config.pad_token_id is None:
            self._model.generation_config.pad_token_id = pad_token_id

        # 检查模型是否有 generate 方法
        if not hasattr(self._model, "generate"):
            raise RuntimeError(
                f"Model {type(self._model).__name__} does not have 'generate' method. "
                f"Please check if the model supports generation or if 'chat' method should be used instead."
            )

        import torch
        try:
            with torch.no_grad():
                output_ids = self._model.generate(
                    **inputs,
                    max_new_tokens=max_tokens,
                    temperature=temperature if temperature > 0 else None,
                    top_p=top_p if temperature > 0 else None,
                    do_sample=temperature > 0,
                    pad_token_id=pad_token_id,
                )
        except RuntimeError as e:
            # 一些极端图像会在 SDPA 触发巨量 buffer 分配；降采样后重试一次。
            if "Invalid buffer size" not in str(e) or not pil_images:
                raise
            smaller = [self._normalize_image(im, max_side=896, max_pixels=786_432) for im in pil_images]
            if len(smaller) == 1:
                retry_inputs = self._processor(
                    text=[text],
                    images=[smaller[0]],
                    padding=True,
                    return_tensors="pt",
                )
            else:
                retry_inputs = self._processor(
                    text=[text],
                    images=[smaller],
                    padding=True,
                    return_tensors="pt",
                )
            retry_inputs = {k: v.to(self._model.device) if hasattr(v, "to") else v for k, v in retry_inputs.items()}
            if "pixel_values" in retry_inputs:
                try:
                    model_dtype = next(self._model.parameters()).dtype
                except StopIteration:
                    model_dtype = self._torch_dtype
                retry_inputs = dict(retry_inputs)
                retry_inputs["pixel_values"] = retry_inputs["pixel_values"].to(model_dtype)
            with torch.no_grad():
                output_ids = self._model.generate(
                    **retry_inputs,
                    max_new_tokens=max_tokens,
                    temperature=temperature if temperature > 0 else None,
                    top_p=top_p if temperature > 0 else None,
                    do_sample=temperature > 0,
                    pad_token_id=pad_token_id,
                )

        # 解码生成部分
        input_len = inputs["input_ids"].shape[1]
        generated = output_ids[:, input_len:]
        result = self._processor.decode(generated[0], skip_special_tokens=True)

        if stop:
            for s in stop:
                if s in result:
                    result = result.split(s)[0].strip()
        return result.strip()

    def unload(self) -> None:
        self._model = None
        self._processor = None
        import gc
        gc.collect()

    @property
    def is_loaded(self) -> bool:
        return self._model is not None
