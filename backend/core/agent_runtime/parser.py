import json
import re
from typing import Dict, Any, Union, Optional
from pydantic import BaseModel, Field

class AgentAction(BaseModel):
    type: str  # "skill_call" | "tool_call" | "final"  (v1.5: Agent 只使用 skill_call；tool_call 在 Loop 中映射为 builtin_<tool>)
    skill_id: Optional[str] = None
    tool: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    answer: Optional[str] = None


def _fix_common_json_errors(json_str: str) -> str:
    """修复常见的 JSON 格式错误，如数组元素之间缺少逗号、字符串内未转义换行。"""
    fixed = json_str

    # 修复0: answer 字符串值内未转义的换行/制表符（Invalid control character）
    answer_match = re.search(r'"answer"\s*:\s*"(.*?)"\s*([}\],\s])', fixed, re.DOTALL)
    if answer_match:
        content = answer_match.group(1)
        if "\n" in content or "\r" in content or "\t" in content:
            escaped = content.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
            fixed = fixed[: answer_match.start(1)] + escaped + fixed[answer_match.end(1) :]

    # 修复1: 数组元素之间缺少逗号
    # 匹配模式: "value"\n\n  "next_value" 或 "value"\n  "next_value"
    # 需要确保是在数组上下文中（前面有 [ 或 ,，后面是 "）
    # 使用更精确的模式：引号 + 可选空白 + 换行 + 可选空白 + 引号（在数组上下文中）
    # 先处理多行情况：引号后换行（可能多个）然后空白然后引号
    fixed = re.sub(
        r'"\s*\n+\s*"',
        '",\n  "',
        fixed
    )
    
    # 修复2: 数组元素之间缺少逗号（同一行，引号后直接空白然后引号）
    # 但要避免匹配字符串内部的引号（这种情况较少，但需要小心）
    # 只在数组上下文中修复：前面是 ] 或 , 或 [，后面是引号
    fixed = re.sub(
        r'(?<=[\[,])\s*"\s+"',
        '", "',
        fixed
    )
    
    # 修复3: 对象属性之间缺少逗号（引号后直接换行后跟引号开头的属性）
    # 匹配: "key": value\n  "next_key"
    fixed = re.sub(
        r'"\s*\n+\s*"([^"]+)":',
        '",\n  "\\1":',
        fixed
    )
    
    # 修复4: 数组最后一个元素后的多余逗号
    fixed = re.sub(r',\s*\]', ']', fixed)
    
    # 修复5: 对象最后一个属性后的多余逗号
    fixed = re.sub(r',\s*}', '}', fixed)
    
    return fixed


def _parse_skill_input_from_text(text: str) -> Dict[str, Any]:
    """从自然语言输出中尽量提取 skill 输入（如 path=...、image=...），否则返回空 dict。"""
    out: Dict[str, Any] = {}
    # path="苹果.txt" 或 path: 苹果.txt 或 path=苹果.txt
    path_quoted = re.search(r'path\s*=\s*["\']([^"\']+)["\']', text, re.IGNORECASE)
    if path_quoted:
        out["path"] = path_quoted.group(1).strip()
        return out
    path_unquoted = re.search(r'path\s*[=:]\s*(\S+)', text, re.IGNORECASE)
    if path_unquoted:
        out["path"] = path_unquoted.group(1).strip().rstrip(".,;")
        return out
    # image="xxx.jpg" 或 image: xxx.jpg（vision.detect_objects）
    image_quoted = re.search(r'image\s*=\s*["\']([^"\']+)["\']', text, re.IGNORECASE)
    if image_quoted:
        out["image"] = image_quoted.group(1).strip()
        return out
    # 任意引号包裹的常见图像文件名
    image_file = re.search(r'["\']([a-zA-Z0-9_.-]+\.(?:jpg|jpeg|png|gif|webp|bmp))["\']', text, re.IGNORECASE)
    if image_file and "vision" in text.lower():
        out["image"] = image_file.group(1).strip()
        return out
    return out


def parse_llm_output(output: str, strict_mode: bool = False) -> AgentAction:
    """
    解析 LLM 输出，识别 Action 或 Final Answer
    支持格式：
    1. 纯 JSON
    2. Markdown 代码块中的 JSON
    3. <think>...</think> 标签包裹的思考过程（提取标签外的内容）
    4. 纯文本（自动包装为 final answer）
    """
    # 检查空输出
    if not output or not output.strip():
        raise ValueError("Invalid agent output (must be JSON action): Empty output")
    
    # 处理 <think> 标签：提取标签外的内容
    # 如果整个输出都被 <think> 包裹，尝试提取标签后的内容
    think_pattern = r'<think>.*?</think>'
    think_matches = list(re.finditer(think_pattern, output, re.DOTALL | re.IGNORECASE))
    
    if think_matches:
        # 移除所有 <think>...</think> 标签，保留标签外的内容
        cleaned_output = re.sub(think_pattern, '', output, flags=re.DOTALL | re.IGNORECASE).strip()
        
        # 如果移除标签后内容为空，说明整个输出都在 think 标签内
        # 这种情况下，尝试提取最后一个 </think> 后的内容
        if not cleaned_output:
            # 提取最后一个 </think> 后的内容
            last_think_end = output.rfind('</think>')
            if last_think_end != -1:
                cleaned_output = output[last_think_end + 8:].strip()  # 8 = len('</think>')
        
        # 如果还是没有内容，说明整个输出都是思考过程，没有实际的 action
        # 这种情况下，在严格模式下应该报错而不是尝试提取内容
        if not cleaned_output:
            if strict_mode:
                raise ValueError(f"Invalid agent output (strict mode): All content wrapped in think tags. Raw output: {output[:500]}")
            # 尝试从最后一个 think 标签中提取可能的 JSON
            # 有些模型会在 think 标签内包含 JSON
            last_match = think_matches[-1]
            think_content = last_match.group(0)  # 包含标签本身
            # 在 think 内容中查找 JSON
            json_in_think = re.search(r'\{[^{}]*"type"[^{}]*\}', think_content, re.DOTALL)
            if json_in_think:
                cleaned_output = json_in_think.group(0).strip()
            else:
                # 如果 think 标签内也没有 JSON，将整个输出作为错误处理
                # 但先尝试提取 think 标签后的内容（可能标签没有正确闭合）
                # 或者尝试提取 think 标签内的内容作为 final answer
                think_content_only = re.sub(r'</?think>', '', think_content, flags=re.IGNORECASE).strip()
                if think_content_only:
                    # 在严格模式下不应该将思考内容作为最终答案
                    if strict_mode:
                        raise ValueError(f"Invalid agent output (strict mode): Think content cannot be used as final answer. Raw output: {output[:500]}")
                    # 将思考内容作为 final answer（虽然不理想，但比报错好）
                    cleaned_output = think_content_only
        
        output = cleaned_output if cleaned_output else output
    
    # 尝试提取 Markdown 代码块中的 JSON
    json_match = re.search(r'```json\s*(.*?)\s*```', output, re.DOTALL)
    if json_match:
        content = json_match.group(1).strip()
    else:
        # 尝试寻找最外层的 {}
        start = output.find('{')
        end = output.rfind('}')
        if start != -1 and end != -1:
            content = output[start:end+1].strip()
        else:
            content = output.strip()

    # 再次检查内容是否为空
    if not content:
        raise ValueError(f"Invalid agent output (must be JSON action): No JSON found in output: {output[:200]}")

    # 若内容明显不是 JSON（不以 { 或 [ 开头），视为纯文本最终答案（如 VLM OCR 非 JSON 输出）
    content_stripped = content.strip()
    if content_stripped and content_stripped[0] not in '{[':
        return AgentAction(type="final", answer=output.strip())

    try:
        data = json.loads(content)
        
        # 检查是否有 type 字段
        if "type" not in data:
            # 如果没有 type 字段，可能是 LLM 直接返回了结果对象（如 VLM 输出）
            # 尝试将其包装为 final answer
            if "raw_text" in data:
                # 看起来是 OCR/VLM 的结构化输出，提取 raw_text 作为 answer
                answer_text = str(data.get("raw_text", ""))
                if not answer_text and "lines" in data and isinstance(data["lines"], list):
                    # 如果没有 raw_text，尝试从 lines 中提取
                    answer_text = " ".join(str(line) for line in data["lines"] if line)
                if answer_text:
                    return AgentAction(type="final", answer=answer_text)
            elif "text" in data:
                # 可能是 VLM 的输出格式
                return AgentAction(type="final", answer=str(data.get("text", "")))
            elif "answer" in data:
                # 有 answer 字段但没有 type，可能是格式错误
                answer_value = data["answer"]
                if isinstance(answer_value, dict):
                    if "raw_text" in answer_value:
                        return AgentAction(type="final", answer=str(answer_value["raw_text"]))
                    elif "text" in answer_value:
                        return AgentAction(type="final", answer=str(answer_value["text"]))
                return AgentAction(type="final", answer=str(answer_value))
            else:
                # 无法识别格式，在严格模式下报错
                if strict_mode:
                    raise ValueError(f"Invalid agent output (strict mode): Missing 'type' field. Raw output: {output[:500]}")
                # 非严格模式：尝试将整个对象转换为字符串作为 answer
                import json as json_module
                return AgentAction(type="final", answer=json_module.dumps(data, ensure_ascii=False))
        
        # 兼容 skill_call 的 args 字段
        if "args" in data and "input" not in data and data.get("type") == "skill_call":
            data = {**data, "input": data.pop("args", {})}
        if data.get("type") == "skill_call" and "skill_id" not in data and "skill" in data:
            data = {**data, "skill_id": data.get("skill")}
        # 处理 answer 字段：如果是对象/字典，转换为字符串
        if data.get("type") == "final" and "answer" in data:
            answer_value = data["answer"]
            if isinstance(answer_value, dict):
                # 如果 answer 是对象，尝试提取关键信息
                # 优先提取 raw_text，否则提取所有文本字段
                if "raw_text" in answer_value:
                    data["answer"] = str(answer_value["raw_text"])
                elif "text" in answer_value:
                    data["answer"] = str(answer_value["text"])
                elif "content" in answer_value:
                    data["answer"] = str(answer_value["content"])
                else:
                    # 将整个对象转换为 JSON 字符串
                    import json as json_module
                    data["answer"] = json_module.dumps(answer_value, ensure_ascii=False)
            elif not isinstance(answer_value, str):
                # 如果不是字符串也不是字典，转换为字符串
                data["answer"] = str(answer_value)
        action = AgentAction(**data)
    except (json.JSONDecodeError, ValueError) as e:
        # JSON 解析失败或 AgentAction 验证失败
        # 尝试修复常见的 JSON 格式错误
        if isinstance(e, json.JSONDecodeError):
            try:
                # 使用修复函数尝试修复 JSON
                fixed_content = _fix_common_json_errors(content)
                
                # 如果修复了内容，再次尝试解析
                if fixed_content != content:
                    try:
                        data = json.loads(fixed_content)
                        # 如果修复成功，继续处理
                        if "type" not in data:
                            # 处理缺少 type 字段的情况（复用上面的逻辑）
                            if "raw_text" in data:
                                answer_text = str(data.get("raw_text", ""))
                                if not answer_text and "lines" in data and isinstance(data["lines"], list):
                                    answer_text = " ".join(str(line) for line in data["lines"] if line)
                                if answer_text:
                                    return AgentAction(type="final", answer=answer_text)
                            elif "text" in data:
                                return AgentAction(type="final", answer=str(data.get("text", "")))
                            elif "answer" in data:
                                answer_value = data["answer"]
                                if isinstance(answer_value, dict):
                                    if "raw_text" in answer_value:
                                        return AgentAction(type="final", answer=str(answer_value["raw_text"]))
                                    elif "text" in answer_value:
                                        return AgentAction(type="final", answer=str(answer_value["text"]))
                                return AgentAction(type="final", answer=str(answer_value))
                            else:
                                # 无法识别格式，在严格模式下报错
                                if strict_mode:
                                    raise ValueError(f"Invalid agent output (strict mode): Missing 'type' field after JSON fix. Raw output: {output[:500]}")
                                # 非严格模式：尝试将整个对象转换为字符串作为 answer
                                import json as json_module
                                return AgentAction(type="final", answer=json_module.dumps(data, ensure_ascii=False))
                        else:
                            # 有 type 字段，正常处理
                            # 兼容 skill_call 的 args 字段
                            if "args" in data and "input" not in data and data.get("type") == "skill_call":
                                data = {**data, "input": data.pop("args", {})}
                            if data.get("type") == "skill_call" and "skill_id" not in data and "skill" in data:
                                data = {**data, "skill_id": data.get("skill")}
                            # 处理 answer 字段：如果是对象/字典，转换为字符串
                            if data.get("type") == "final" and "answer" in data:
                                answer_value = data["answer"]
                                if isinstance(answer_value, dict):
                                    if "raw_text" in answer_value:
                                        data["answer"] = str(answer_value["raw_text"])
                                    elif "text" in answer_value:
                                        data["answer"] = str(answer_value["text"])
                                    elif "content" in answer_value:
                                        data["answer"] = str(answer_value["content"])
                                    else:
                                        import json as json_module
                                        data["answer"] = json_module.dumps(answer_value, ensure_ascii=False)
                                elif not isinstance(answer_value, str):
                                    data["answer"] = str(answer_value)
                            action = AgentAction(**data)
                            return action
                    except (json.JSONDecodeError, ValueError) as fix_error:
                        # 修复后仍然失败，继续原有错误处理流程
                        pass
            except Exception:
                # 修复过程出错，继续原有错误处理流程
                pass
        # JSON 解析失败：检查是否是因为 JSON 被截断（不完整）
        # 检查是否有开始但未闭合的 JSON 结构
        open_braces = content.count('{')
        close_braces = content.count('}')
        is_truncated = open_braces > close_braces
        
        # 如果 JSON 被截断，尝试提取已解析的部分
        if is_truncated:
            # 检查是否包含 type: "final" 的结构
            if '"type"' in content and '"final"' in content:
                # 尝试从截断的 JSON 中提取 answer 字段
                # 查找 "answer": " 之后的内容
                answer_pattern = r'"answer"\s*:\s*"(.*?)(?:"|$)'
                answer_match = re.search(answer_pattern, content, re.DOTALL)
                
                if answer_match:
                    # 提取 answer 值（可能不完整）
                    answer_value = answer_match.group(1)
                    # 处理转义字符
                    answer_value = answer_value.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t')
                    return AgentAction(
                        type="final",
                        answer=answer_value.strip()
                    )
                
                # 如果无法提取 answer，尝试从原始输出中提取（去掉 JSON 标记）
                # 移除 ```json 和开头的 JSON 结构
                cleaned_output = re.sub(r'```json\s*', '', output, flags=re.IGNORECASE)
                cleaned_output = re.sub(r'```\s*$', '', cleaned_output, flags=re.IGNORECASE)
                # 尝试找到 answer 字段的值
                answer_start = cleaned_output.find('"answer"')
                if answer_start != -1:
                    # 找到第一个引号后的内容
                    quote_start = cleaned_output.find('"', answer_start + 8)  # 跳过 "answer"
                    if quote_start != -1:
                        # 提取引号后的内容（到字符串结尾，因为被截断了）
                        answer_text = cleaned_output[quote_start + 1:]
                        return AgentAction(
                            type="final",
                            answer=answer_text.strip()
                        )
                
                # 最后回退：使用整个原始输出（去掉代码块标记）
                cleaned = re.sub(r'```json\s*', '', output, flags=re.IGNORECASE)
                cleaned = re.sub(r'```\s*$', '', cleaned, flags=re.IGNORECASE)
                cleaned = re.sub(r'^\s*\{\s*"type"\s*:\s*"final"\s*,\s*"answer"\s*:\s*"', '', cleaned)
                return AgentAction(
                    type="final",
                    answer=cleaned.strip()
                )
        
        # 自然语言 skill/tool 调用兜底（在「视为 final」之前）：LLM 输出 "Calling skill builtin_file.read" 等
        # 支持：Calling skill `builtin_file.read` / 使用 vision.detect_objects 工具
        stripped = output.strip()
        skill_tool_match = re.search(
            r'(?:calling|call|invoking|invoke|using|use|使用)\s*(?:the\s+)?(?:skill|tool|工具)?\s*'
            r'(?:[`\'"]([^`\'"]+)[`\'"]|([a-zA-Z_][a-zA-Z0-9_.]*))',
            stripped,
            re.IGNORECASE
        )
        if skill_tool_match:
            name = (skill_tool_match.group(1) or skill_tool_match.group(2) or "").strip()
            if name:
                if name.startswith("builtin_"):
                    return AgentAction(type="skill_call", skill_id=name, input=_parse_skill_input_from_text(stripped))
                return AgentAction(type="tool_call", tool=name, input=_parse_skill_input_from_text(stripped))
        
        # JSON 解析失败但不是截断：如果输出看起来像是最终答案（没有明显的工具调用意图），
        # 则自动包装为 final answer
        # 但在严格模式下，不应有这种兜底行为
        if strict_mode:
            raise ValueError(f"Invalid agent output (strict mode): JSON decode error: {e}. Raw output: {output[:500]}")
            
        tool_keywords = ['tool_call', 'tool', 'skill_call', 'skill', 'input', 'type', '调用工具', '使用工具']
        has_tool_intent = any(keyword in content.lower() for keyword in tool_keywords)
        
        # 如果输出很短且不包含工具调用意图，视为最终答案
        if not has_tool_intent and len(content) < 5000:
            return AgentAction(type="final", answer=output.strip())
        
        # 兜底：仅匹配 "tool" 的旧格式（带反引号的工具名）
        tool_name_in_text = re.search(
            r'(?:calling|call|invoking|invoke|using|use)\s+(?:the\s+)?tool\s+[`\'"]([^`\'"]+)[`\'"]',
            stripped,
            re.IGNORECASE
        )
        if tool_name_in_text:
            tool_name = tool_name_in_text.group(1).strip()
            if tool_name:
                return AgentAction(type="tool_call", tool=tool_name, input={})
        
        # 否则抛出错误
        raise ValueError(f"Invalid agent output (must be JSON action): JSON decode error: {e}. Raw output: {output[:500]}")
    except Exception as e:
        # 其他错误：同样尝试自动包装
        if isinstance(e, ValueError) and "JSON decode error" in str(e):
            raise  # 重新抛出上面的 ValueError
        
        # 在严格模式下，不应有兜底行为
        if strict_mode:
            raise ValueError(f"Invalid agent output (strict mode): {e}. Raw output: {output[:500]}")
            
        # 对于其他异常，也尝试自动包装为 final answer
        return AgentAction(
            type="final",
            answer=output.strip()
        )

    # 强约束：允许 skill_call / tool_call / final
    if action.type not in {"skill_call", "tool_call", "final"}:
        raise ValueError(f"Invalid agent action type: {action.type}")
    if action.type == "skill_call" and not action.skill_id:
        raise ValueError("skill_call action missing 'skill_id'")
    if action.type == "tool_call" and not action.tool:
        raise ValueError("tool_call action missing 'tool'")
    if action.type == "final" and action.answer is None:
        raise ValueError("final action missing 'answer'")

    return action
