"""
InternVLAdapter: InternVL2 / InternVL3 模型适配器

使用 AutoModel / InternVLChatModel，processor 负责 image + text。
支持 <image> 占位符或 messages + images 映射。
"""

import base64
from io import BytesIO
from pathlib import Path
from typing import Dict, Any, List, Optional, Union

try:
    from PIL import Image
except ImportError:
    Image = None

from .model_adapter import ModelAdapter


def _load_image(source: Union[str, bytes, "Image.Image"]) -> "Image.Image":
    """将路径/bytes/PIL 转为 PIL.Image"""
    if Image is None:
        raise RuntimeError("PIL not installed")
    if isinstance(source, Image.Image):
        return source.convert("RGB")
    if isinstance(source, bytes):
        return Image.open(BytesIO(source)).convert("RGB")
    if isinstance(source, str):
        return Image.open(source).convert("RGB")
    raise ValueError(f"Unsupported image type: {type(source)}")


def _extract_images_from_messages(
    messages: List[Dict[str, Any]],
    images: Optional[List[Union[str, bytes, "Image.Image"]]],
) -> tuple[List["Image.Image"], List[Dict[str, Any]]]:
    """
    从 messages + images 提取图像列表，并构建 adapter 可用的 messages。

    规则：
    1. 若 content 为 array，其中 image_url 的 url 若为 data:...base64，解码为 PIL
    2. 若 content 为 array 中有 image_url 但无 data，或 content 为 str，则从 images 中按序取
    3. 返回 (pil_images, processed_messages)，processed_messages 中图像位置用占位符或索引表示
    """
    if Image is None:
        return [], messages

    pil_list: List["Image.Image"] = []
    img_idx = 0

    def _process_content(content: Any) -> Any:
        nonlocal img_idx
        if isinstance(content, str):
            # 纯文本，若 images 有剩余则按 <image> 占位符插入
            # 简化：不自动插入，由调用方保证 content 含 <image> 时 images 足够
            return content
        if isinstance(content, list):
            out = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "image_url":
                        url = (item.get("image_url") or {}).get("url", "")
                        if url.startswith("data:"):
                            # data:image/png;base64,xxx
                            b64 = url.split(",", 1)[-1]
                            raw = base64.b64decode(b64)
                            pil_list.append(_load_image(raw))
                            out.append({"type": "image", "image": pil_list[-1]})
                        elif images and img_idx < len(images):
                            pil_list.append(_load_image(images[img_idx]))
                            img_idx += 1
                            out.append({"type": "image", "image": pil_list[-1]})
                    elif item.get("type") == "text":
                        out.append(item)
                else:
                    out.append(item)
            return out
        return content

    processed = []
    for msg in messages:
        c = msg.get("content")
        if c is not None:
            msg = {**msg, "content": _process_content(c)}
        processed.append(msg)

    # 若 content 为 str 且 images 有提供，将首条 user 消息改为 [image1, image2, ..., text]
    if images and img_idx < len(images):
        for m in processed:
            if m.get("role") == "user":
                extra = [_load_image(images[i]) for i in range(img_idx, len(images))]
                pil_list.extend(extra)
                img_idx = len(images)
                c = m.get("content")
                if isinstance(c, str):
                    new_m = {**m, "content": [{"type": "image", "image": im} for im in extra] + [{"type": "text", "text": c}]}
                    new_processed = []
                    replaced = False
                    for x in processed:
                        if not replaced and x.get("role") == "user" and x.get("content") == c:
                            new_processed.append(new_m)
                            replaced = True
                        else:
                            new_processed.append(x)
                    processed = new_processed
                break

    return pil_list, processed


def _try_fix_mistral_regex(tokenizer: Any, model_name: str):
    """
    兼容 transformers 对 mistral regex 的修复入口差异。
    某些版本传 fix_mistral_regex 参数会报 duplicated kwargs，这里改为后置补丁调用。
    """
    try:
        patcher = getattr(type(tokenizer), "_patch_mistral_regex", None)
        if callable(patcher):
            patched = patcher(
                tokenizer,
                model_name,
                local_files_only=True,
                is_local=True,
                fix_mistral_regex=True,
            )
            if patched is not None:
                return patched
    except Exception:
        pass
    return tokenizer


class InternVLAdapter(ModelAdapter):
    """
    InternVL 系列适配器（InternVL2、InternVL3）

    使用 transformers 的 AutoModel + AutoProcessor。
    """

    def __init__(self):
        self._model = None
        self._processor = None
        self._tokenizer = None
        self._image_processor = None
        self._model_name: Optional[str] = None
        self._device: str = "auto"
        self._torch_dtype = None

    def load(self, model_dir: Path, options: Dict[str, Any]) -> None:
        import torch
        from transformers import AutoModel, AutoProcessor, AutoTokenizer, AutoImageProcessor, AutoConfig

        model_name = options.get("model_name") or str(model_dir)
        torch_dtype_str = (options.get("torch_dtype") or "float16").lower()
        requested_dtype = getattr(torch, torch_dtype_str, torch.float16)
        self._device = options.get("device", "auto")
        self._model_name = model_name
        if self._device == "auto":
            if torch.cuda.is_available():
                self._device = "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                self._device = "mps"
            else:
                self._device = "cpu"

        # CPU 下 float16 容易导致数值异常（乱码/重复字符），强制回退到 float32。
        self._torch_dtype = requested_dtype
        if self._device == "cpu" and requested_dtype == torch.float16:
            self._torch_dtype = torch.float32

        # 注意：部分 InternVL3 模型的 AutoProcessor 可能退化为 tokenizer 本身，
        # 因此这里同时显式加载 tokenizer + image_processor，推理优先走 model.chat()
        self._processor = AutoProcessor.from_pretrained(model_name, trust_remote_code=True)
        # 使用 slow tokenizer，降低 fast-tokenizer 正则兼容性问题风险。
        self._tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            trust_remote_code=True,
            use_fast=False,
        )
        self._tokenizer = _try_fix_mistral_regex(self._tokenizer, model_name)
        proc_tok = getattr(self._processor, "tokenizer", None)
        if proc_tok is not None:
            setattr(self._processor, "tokenizer", _try_fix_mistral_regex(proc_tok, model_name))
        try:
            self._image_processor = AutoImageProcessor.from_pretrained(model_name, trust_remote_code=True)
        except Exception:
            # 有些权重没有单独的 image processor 配置，后续会在 generate 中按需处理
            self._image_processor = None

        # transformers>=5 默认会在 meta device 上初始化模型。
        # InternVL3 的 remote code 在 __init__ 中执行 tensor.item()，会触发:
        # "Tensor.item() cannot be called on meta tensors"。
        # 这里对 InternVL 类做定向兼容，不影响其它模型。
        try:
            cfg = AutoConfig.from_pretrained(model_name, trust_remote_code=True)
            auto_map = getattr(cfg, "auto_map", {}) or {}
            auto_model_ref = auto_map.get("AutoModel")
        except Exception:
            cfg = None
            auto_model_ref = None

        if auto_model_ref:
            try:
                from transformers.dynamic_module_utils import get_class_from_dynamic_module
                from transformers.modeling_utils import local_torch_dtype, init

                model_cls = get_class_from_dynamic_module(auto_model_ref, model_name)
                orig_init = model_cls.__init__

                def _patched_init(this, *args, **kwargs):
                    orig_init(this, *args, **kwargs)
                    if not hasattr(this, "all_tied_weights_keys"):
                        this.all_tied_weights_keys = {}

                def _compat_init_context(cls_, dtype, is_quantized, _is_ds_init_called, allow_all_kernels=False):
                    # 去掉 meta 初始化，同时保留 no_init_weights，避免先随机初始化再覆盖导致的潜在数值漂移。
                    # allow_all_kernels: transformers 新版本 get_init_context 第 5 个参数，此处兼容签名即可。
                    return [local_torch_dtype(dtype, cls_.__name__), init.no_tie_weights(), init.no_init_weights()]

                model_cls.__init__ = _patched_init
                model_cls.get_init_context = classmethod(_compat_init_context)
                self._model = model_cls.from_pretrained(
                    model_name,
                    torch_dtype=self._torch_dtype,
                    trust_remote_code=True,
                    low_cpu_mem_usage=False,
                )
            except Exception:
                self._model = AutoModel.from_pretrained(
                    model_name,
                    torch_dtype=self._torch_dtype,
                    trust_remote_code=True,
                    low_cpu_mem_usage=False,
                )
        else:
            self._model = AutoModel.from_pretrained(
                model_name,
                torch_dtype=self._torch_dtype,
                trust_remote_code=True,
                low_cpu_mem_usage=False,
            )
        self._model = self._model.to(self._device)
        self._model.eval()

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

        # --- 优先走 InternVL 官方 chat() 路径（最稳，避免 tokenizer(images=...) / IMG_CONTEXT 拼接问题） ---
        tokenizer = self._tokenizer or getattr(self._processor, "tokenizer", self._processor)
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
            # 简单拼接 system，避免丢失用户自定义 system
            question = f"{system_prompt}\n\n{question}"

        pixel_values = None
        if pil_images:
            img_proc = (
                getattr(self._processor, "image_processor", None)
                or getattr(self._processor, "vision_processor", None)
                or self._image_processor
            )
            if not img_proc:
                raise RuntimeError("No image processor available for InternVL model.")
            # 只取第一张图（与当前前端/接口约束一致）
            image_input = pil_images[0]
            out = img_proc(images=image_input, return_tensors="pt")
            pixel_values = out.get("pixel_values") if hasattr(out, "get") else getattr(out, "pixel_values", None)
            if pixel_values is None:
                raise RuntimeError("image_processor did not return pixel_values")

            # dtype/device 对齐
            try:
                model_dtype = next(self._model.parameters()).dtype
            except StopIteration:
                model_dtype = self._torch_dtype
            pixel_values = pixel_values.to(device=self._model.device, dtype=model_dtype)

        do_sample = float(temperature) > 0 and self._device != "cpu"
        generation_config = {
            "max_new_tokens": int(max_tokens),
            "temperature": float(temperature if do_sample else 0.0),
            "top_p": float(top_p if do_sample else 1.0),
            "do_sample": do_sample,
        }

        if hasattr(self._model, "chat"):
            import torch
            with torch.no_grad():
                # 兼容不同 InternVL 版本的 chat() 签名
                for args, kwargs in [
                    ((tokenizer, pixel_values, question, generation_config), {}),
                    ((tokenizer, pixel_values, question, generation_config), {"history": None}),
                    ((tokenizer, pixel_values, question, generation_config), {"history": None, "return_history": False}),
                    ((tokenizer, pixel_values, question, generation_config), {"history": None, "return_history": True}),
                ]:
                    try:
                        out = self._model.chat(*args, **kwargs)
                        if isinstance(out, tuple):
                            return (out[0] or "").strip()
                        return (out or "").strip()
                    except TypeError:
                        continue
            # 如果 chat 存在但全部签名都失败，继续走旧路径（尽量不直接报错）

        # --- 旧路径保留：用于极少数没有 chat() 的权重 ---
        prompt = None
        if hasattr(self._processor, "apply_chat_template"):
            try:
                prompt = self._processor.apply_chat_template(
                    processed_messages,
                    tokenize=False,
                    add_generation_prompt=True,
                )
            except (TypeError, ValueError):
                pass
        if not prompt:
            prompt = question

        if pil_images:
            image_input = pil_images[0] if len(pil_images) == 1 else pil_images
            try:
                inputs = self._processor(text=prompt, images=image_input, return_tensors="pt").to(self._model.device)
            except (TypeError, AttributeError) as e:
                if "images" in str(e).lower() or "tokenizer" in str(e).lower():
                    inputs = self._processor_with_images_fallback(prompt, image_input)
                else:
                    raise
        else:
            inputs = self._processor(text=prompt, return_tensors="pt").to(self._model.device)

        # 兼容 processor.tokenizer 与 processor 即 tokenizer 两种结构（InternVL3 等）
        tok = getattr(self._processor, "tokenizer", self._processor)
        pad_token_id = getattr(tok, "pad_token_id", None) or getattr(tok, "eos_token_id", None)
        # 避免 transformers 内部打印 "Setting pad_token_id to eos_token_id for open-end generation"
        if getattr(tok, "pad_token_id", None) is None and pad_token_id is not None:
            tok.pad_token_id = pad_token_id
        if getattr(self._model, "generation_config", None) is not None and self._model.generation_config.pad_token_id is None:
            self._model.generation_config.pad_token_id = pad_token_id

        # InternVL3 generate() 需要 img_context_token_id，若未设置则从 tokenizer 获取
        if hasattr(self._model, "img_context_token_id") and self._model.img_context_token_id is None:
            unk_id = getattr(tok, "unk_token_id", None)
            for placeholder in ("<<IMG_CONTEXT>>", "<img>", "<|im_pixel|>"):
                ids = tok.encode(placeholder, add_special_tokens=False)
                if ids and (unk_id is None or ids[0] != unk_id):
                    self._model.img_context_token_id = ids[0]
                    break
            if self._model.img_context_token_id is None and hasattr(self._model.config, "img_context_token_id"):
                self._model.img_context_token_id = self._model.config.img_context_token_id

        # 确保 pixel_values 与模型 dtype 一致（vision 期望 bfloat16/float16）
        if "pixel_values" in inputs:
            try:
                model_dtype = next(self._model.parameters()).dtype
            except StopIteration:
                model_dtype = self._torch_dtype
            if inputs["pixel_values"].dtype != model_dtype:
                inputs = dict(inputs)  # BatchFeature 可能不可变，转为 dict 再修改
                inputs["pixel_values"] = inputs["pixel_values"].to(model_dtype)

        with __import__("torch").no_grad():
            output_ids = self._model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                do_sample=temperature > 0,
                pad_token_id=pad_token_id,
            )

        # 只解码新生成部分
        input_len = inputs["input_ids"].shape[1]
        generated = output_ids[:, input_len:]
        text = self._processor.decode(generated[0], skip_special_tokens=True)

        if stop:
            for s in stop:
                if s in text:
                    text = text.split(s)[0].strip()
        return text.strip()

    def _processor_with_images_fallback(self, prompt: str, image_input: Union["Image.Image", List["Image.Image"]]) -> Dict[str, Any]:
        """当 processor(text, images=...) 触发 tokenizer 的 images 参数错误时，分离调用 image_processor 与 tokenizer"""
        img_proc = (
            getattr(self._processor, "image_processor", None)
            or getattr(self._processor, "vision_processor", None)
        )
        if not img_proc:
            if self._image_processor is None:
                try:
                    from transformers import AutoImageProcessor
                    self._image_processor = AutoImageProcessor.from_pretrained(self._model_name, trust_remote_code=True)
                except Exception as e:
                    raise RuntimeError(f"processor has no image_processor and AutoImageProcessor.from_pretrained failed: {e}")
            img_proc = self._image_processor
        tok = getattr(self._processor, "tokenizer", self._processor)
        pixel_values = None
        for args, kwargs in [
            ((), {"images": image_input, "return_tensors": "pt"}),
            ((), {"image": image_input, "return_tensors": "pt"}),
            ((image_input,), {"return_tensors": "pt"}),
        ]:
            try:
                out = img_proc(*args, **kwargs)
            except (TypeError, ValueError):
                continue
            pixel_values = out.get("pixel_values") if hasattr(out, "get") else getattr(out, "pixel_values", None)
            if pixel_values is not None:
                break
        if pixel_values is None:
            raise RuntimeError("image_processor did not return pixel_values")
        # InternVL 需在 prompt 中插入 N 个 <<IMG_CONTEXT>> 占位符，N 必须与 vision 输出的 token 数一致
        # 先跑一次 vision 获取 num_vision_tokens，再构建含正确数量占位符的 input_ids
        import torch
        try:
            model_dtype = next(self._model.parameters()).dtype
        except StopIteration:
            model_dtype = self._torch_dtype
        with torch.no_grad():
            pv = pixel_values.to(device=self._model.device, dtype=model_dtype)
            vit_embeds = self._model.extract_feature(pv)
            num_vision_tokens = vit_embeds.shape[1] if vit_embeds.dim() > 1 else vit_embeds.shape[0]
        ctx_id = None
        for ph in ("<<IMG_CONTEXT>>", "<img>", "<|im_pixel|>"):
            ids = tok.encode(ph, add_special_tokens=False)
            if ids:
                ctx_id = ids[0]
                break
        if ctx_id is None:
            ctx_id = getattr(self._model, "img_context_token_id", None) or getattr(self._model.config, "img_context_token_id", None)
        if ctx_id is None:
            raise RuntimeError("Cannot determine img_context_token_id for InternVL")
        placeholder_ids = [ctx_id] * num_vision_tokens
        prompt_ids = tok.encode(prompt, add_special_tokens=False)
        # 过滤掉 prompt 中已有的 img_context_token，确保仅保留我们添加的 num_vision_tokens 个
        prompt_ids = [t for t in prompt_ids if t != ctx_id]
        input_ids = torch.tensor([placeholder_ids + prompt_ids], dtype=torch.long, device=self._model.device)
        inputs = {"input_ids": input_ids, "pixel_values": pixel_values}
        inputs["attention_mask"] = torch.ones_like(input_ids, device=self._model.device)
        device = self._model.device
        try:
            model_dtype = next(self._model.parameters()).dtype
        except StopIteration:
            model_dtype = self._torch_dtype
        # pixel_values 需与模型 dtype 一致（vision 期望 bfloat16/float16，image_processor 默认 float32）
        result = {"pixel_values": pixel_values.to(device=device, dtype=model_dtype)}
        for k, v in inputs.items():
            if k != "pixel_values":
                result[k] = v.to(device) if hasattr(v, "to") else v
        return result

    def unload(self) -> None:
        self._model = None
        self._processor = None
        self._tokenizer = None
        self._image_processor = None
        import gc
        gc.collect()

    @property
    def is_loaded(self) -> bool:
        return self._model is not None
