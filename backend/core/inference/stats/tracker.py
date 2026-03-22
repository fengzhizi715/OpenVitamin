"""
V2.8 Inference Gateway Layer - Inference Stats Tracker

Tracks inference performance metrics for system monitoring.
"""
import time
from dataclasses import dataclass, field
from typing import Optional
from collections import deque
import threading


@dataclass
class InferenceRecord:
    """Single inference record"""
    timestamp: float
    tokens: int  # Estimated or actual token count
    latency_ms: float
    tokens_per_second: float
    model: str
    provider: str


class InferenceStatsTracker:
    """
    Thread-safe inference statistics tracker.
    
    Tracks:
    - Last inference speed (tokens/s)
    - Moving average of inference speed
    - Recent inference history (sliding window)
    
    Usage:
        tracker = get_inference_stats()
        
        # Record an inference
        tracker.record(
            tokens=150,
            latency_ms=2000,
            model="deepseek-r1",
            provider="openai"
        )
        
        # Get current speed
        speed = tracker.get_tokens_per_second()
    """
    
    def __init__(self, window_size: int = 10):
        """
        Initialize the tracker.
        
        Args:
            window_size: Number of recent inferences to keep for moving average
        """
        self._lock = threading.Lock()
        self._window_size = window_size
        self._records: deque = deque(maxlen=window_size)
        self._last_speed: Optional[float] = None
        self._last_timestamp: Optional[float] = None
        self._total_tokens: int = 0
        self._total_inferences: int = 0
    
    def record(
        self,
        tokens: int,
        latency_ms: float,
        model: str = "",
        provider: str = ""
    ) -> None:
        """
        Record an inference event.
        
        Args:
            tokens: Number of tokens generated (estimated or actual)
            latency_ms: Inference latency in milliseconds
            model: Model identifier
            provider: Provider identifier
        """
        if tokens <= 0 or latency_ms <= 0:
            return
        
        tps = (tokens / latency_ms) * 1000  # tokens per second
        
        with self._lock:
            record = InferenceRecord(
                timestamp=time.time(),
                tokens=tokens,
                latency_ms=latency_ms,
                tokens_per_second=tps,
                model=model,
                provider=provider,
            )
            self._records.append(record)
            self._last_speed = tps
            self._last_timestamp = time.time()
            self._total_tokens += tokens
            self._total_inferences += 1
    
    def get_tokens_per_second(self) -> Optional[float]:
        """
        Get the most recent inference speed.
        
        Returns:
            Tokens per second, or None if no inferences recorded
        """
        with self._lock:
            return self._last_speed
    
    def get_average_tokens_per_second(self) -> Optional[float]:
        """
        Get the moving average inference speed.
        
        Returns:
            Average tokens per second over recent inferences, or None if no data
        """
        with self._lock:
            if not self._records:
                return None
            total_tps = sum(r.tokens_per_second for r in self._records)
            return total_tps / len(self._records)
    
    def get_stats(self) -> dict:
        """
        Get comprehensive stats.
        
        Returns:
            Dict with current speed, average, totals, etc.
        """
        with self._lock:
            avg_tps = None
            if self._records:
                total_tps = sum(r.tokens_per_second for r in self._records)
                avg_tps = total_tps / len(self._records)
            
            return {
                "inference_speed": self._last_speed,  # Most recent t/s
                "average_speed": avg_tps,  # Moving average t/s
                "total_tokens": self._total_tokens,
                "total_inferences": self._total_inferences,
                "last_timestamp": self._last_timestamp,
                "window_size": self._window_size,
            }
    
    def reset(self) -> None:
        """Reset all stats"""
        with self._lock:
            self._records.clear()
            self._last_speed = None
            self._last_timestamp = None
            self._total_tokens = 0
            self._total_inferences = 0


# Singleton instance
_tracker: Optional[InferenceStatsTracker] = None
_tracker_lock = threading.Lock()


def get_inference_stats() -> InferenceStatsTracker:
    """Get the global InferenceStatsTracker singleton"""
    global _tracker
    with _tracker_lock:
        if _tracker is None:
            _tracker = InferenceStatsTracker()
        return _tracker


def record_inference(
    tokens: int,
    latency_ms: float,
    model: str = "",
    provider: str = ""
) -> None:
    """
    Convenience function to record an inference.
    
    Args:
        tokens: Number of tokens generated
        latency_ms: Inference latency in milliseconds
        model: Model identifier
        provider: Provider identifier
    """
    get_inference_stats().record(tokens, latency_ms, model, provider)


def estimate_tokens(text: str) -> int:
    """
    Estimate token count from text.
    
    Uses a simple heuristic: ~4 characters per token for most models.
    This is a rough approximation; actual tokenization varies by model.
    
    Args:
        text: The text to estimate tokens for
        
    Returns:
        Estimated token count
    """
    if not text:
        return 0
    # Simple heuristic: ~4 chars per token
    # This works reasonably well for English text
    return max(1, len(text) // 4)
