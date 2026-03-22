"""
V2.8 Inference Gateway Layer - Token Streaming

Unified streaming abstraction for inference responses.
"""
from typing import AsyncIterator, List
from dataclasses import dataclass, field
import time


@dataclass
class TokenStream:
    """
    Unified streaming abstraction.
    
    Collects tokens from async stream and provides:
    - Text accumulation
    - Latency tracking
    - Token counting
    
    Usage:
        stream = TokenStream()
        async for token in provider_stream():
            stream.add_token(token)
        print(stream.text)
        print(f"Latency: {stream.latency_ms:.2f}ms")
    """
    tokens: List[str] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    
    def add_token(self, token: str) -> None:
        """Add a token to the stream"""
        self.tokens.append(token)
    
    @property
    def text(self) -> str:
        """Get accumulated text"""
        return "".join(self.tokens)
    
    @property
    def latency_ms(self) -> float:
        """Get elapsed time in milliseconds"""
        return (time.time() - self.start_time) * 1000
    
    @property
    def token_count(self) -> int:
        """Get number of tokens"""
        return len(self.tokens)
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "text": self.text,
            "tokens": self.tokens,
            "token_count": self.token_count,
            "latency_ms": self.latency_ms,
        }


async def collect_stream(stream: AsyncIterator[str]) -> TokenStream:
    """
    Collect an async token stream into a TokenStream.
    
    Args:
        stream: Async iterator of token strings
        
    Returns:
        TokenStream with all collected tokens
    """
    ts = TokenStream()
    async for token in stream:
        ts.add_token(token)
    return ts


async def stream_to_text(stream: AsyncIterator[str]) -> str:
    """
    Collect an async token stream into plain text.
    
    Args:
        stream: Async iterator of token strings
        
    Returns:
        Concatenated text string
    """
    tokens = []
    async for token in stream:
        tokens.append(token)
    return "".join(tokens)
