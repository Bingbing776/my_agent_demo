"""Abstract base class for LLM providers.

This module defines the pluggable interface for Language Model providers,
enabling seamless switching between different backends (OpenAI, Azure, Ollama, etc.)
through configuration-driven instantiation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class Message:
    """Represents a single message in a chat conversation.
    定义聊天消息的标准格式，统一角色和内容结构。
    
    Attributes:
        role: The role of the message sender ('system', 'user', or 'assistant').
        content: The text content of the message.
    """
    role: str
    content: str


@dataclass
class ChatResponse:
    """Response from an LLM chat completion.
    定义LLM响应的标准格式，包含回复内容、模型信息和其他元数据。
    
    Attributes:
        content: The generated text response. AI生成的回复文本
        model: The model identifier that generated the response.
        usage: Optional token usage statistics (prompt_tokens, completion_tokens, total_tokens). 可选：token使用统计
        raw_response: Optional raw response from the provider for debugging.可选：原始响应数据
    """
    content: str
    model: str
    usage: Optional[Dict[str, int]] = None
    raw_response: Optional[Any] = None


class BaseLLM(ABC):
    """Abstract base class for LLM providers.
    定义所有LLM实现的统一接口规范，确保不同提供商的LLM行为一致。
    
    All LLM implementations must inherit from this class and implement
    the chat() method. This ensures consistent interface across different
    providers (OpenAI, Azure, DeepSeek, Ollama, etc.).
    
    Design Principles Applied:
    - Pluggable: Subclasses can be swapped without changing upstream code.
    - Observable: Accepts optional TraceContext for observability integration.
    - Config-Driven: Instances are created via factory based on settings.
    """
    
    @abstractmethod
    def chat(
        self,
        messages: List[Message],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Generate a chat completion response.接收消息列表，调用LLM生成回复，返回标准化响应。
        
        Args:
            messages: List of conversation messages (role + content).
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Provider-specific parameters (temperature, max_tokens, etc.).
        
        Returns:
            ChatResponse containing the generated text and metadata.
        
        Raises:
            ValueError: If messages list is empty or malformed.
            RuntimeError: If the LLM provider call fails.
        """
        pass
    
    def validate_messages(self, messages: List[Message]) -> None:
        """Validate message list structure.
        验证消息格式 - 检查消息列表是否有效（非空、角色正确、内容不为空）。
        
        Args:
            messages: List of messages to validate.
        
        Raises:
            ValueError: If messages list is empty or contains invalid roles.
        """
        if not messages:
            raise ValueError("Messages list cannot be empty")
        
        valid_roles = {"system", "user", "assistant"}
        for i, msg in enumerate(messages):
            if not isinstance(msg, Message):
                raise ValueError(f"Message at index {i} is not a Message instance")
            if msg.role not in valid_roles:
                raise ValueError(
                    f"Message at index {i} has invalid role '{msg.role}'. "
                    f"Must be one of: {valid_roles}"
                )
            if not msg.content or not msg.content.strip():
                raise ValueError(f"Message at index {i} has empty content")
