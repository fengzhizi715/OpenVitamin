#!/usr/bin/env python3
"""
Inference Gateway Layer 的 HTTP 校验脚本。

用法（需先启动后端）：
    cd backend && python scripts/test_inference_gateway.py
    或：python scripts/test_inference_gateway.py --base-url http://localhost:8000

校验项：
  1. GET /api/system/metrics 包含 inference_speed（可为 null）
  2. 使用一个 LLM 模型发一次 Chat 请求
  3. 再次 GET /api/system/metrics，inference_speed 应为数字
"""
import argparse
import json
import sys

try:
    import httpx
except ImportError:
    print("需要安装 httpx: pip install httpx")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Inference Gateway HTTP 校验")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="后端 base URL（默认 http://localhost:8000）",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="指定 model_id；不传则从 GET /api/models 取第一个 LLM",
    )
    parser.add_argument(
        "--skip-chat",
        action="store_true",
        help="仅检查 metrics 是否包含 inference_speed，不发 Chat",
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    ok = True

    # 1. GET /api/system/metrics
    print("1. GET /api/system/metrics ...")
    try:
        r = httpx.get(f"{base}/api/system/metrics", timeout=10.0)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"   失败: {e}")
        return 1

    if "inference_speed" not in data:
        print("   失败: 响应中缺少 inference_speed 字段")
        ok = False
    else:
        speed = data["inference_speed"]
        print(f"   inference_speed = {speed!r}")

    if args.skip_chat:
        print("   (跳过 Chat，未校验推理后 speed)")
        return 0 if ok else 1

    # 2. 解析 model_id
    model_id = args.model
    if not model_id:
        print("2. GET /api/models?model_type=llm ...")
        try:
            r = httpx.get(f"{base}/api/models", params={"model_type": "llm"}, timeout=10.0)
            r.raise_for_status()
            out = r.json()
            models = out.get("data") or []
            for m in models:
                if m.get("id"):
                    model_id = m["id"]
                    break
        except Exception as e:
            print(f"   失败: {e}")
            return 1
        if not model_id:
            print("   失败: 未找到 LLM 模型，请使用 --model YOUR_MODEL_ID")
            return 1
        print(f"   使用模型: {model_id}")
    else:
        print(f"2. 使用指定模型: {model_id}")

    # 3. POST /v1/chat/completions
    print("3. POST /v1/chat/completions (非流式) ...")
    try:
        r = httpx.post(
            f"{base}/v1/chat/completions",
            json={
                "model": model_id,
                "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
                "stream": False,
                "max_tokens": 20,
            },
            timeout=60.0,
        )
        r.raise_for_status()
        body = r.json()
        content = (body.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        print(f"   响应长度: {len(content)} 字符")
    except Exception as e:
        print(f"   失败: {e}")
        return 1

    # 4. 再次 GET /api/system/metrics
    print("4. GET /api/system/metrics (推理后) ...")
    try:
        r = httpx.get(f"{base}/api/system/metrics", timeout=10.0)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"   失败: {e}")
        return 1

    speed = data.get("inference_speed")
    if speed is None:
        print("   警告: inference_speed 仍为 null（可能请求未走记录统计的路径）")
        ok = False
    elif isinstance(speed, (int, float)):
        print(f"   inference_speed = {speed} (t/s)")
    else:
        print(f"   失败: inference_speed 应为数字，实际为 {type(speed).__name__}")
        ok = False

    print("")
    if ok:
        print("通过：Inference Gateway 相关校验完成。")
    else:
        print("存在告警或失败项，请对照 docs/INFERENCE_GATEWAY_TESTING.md 排查。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
