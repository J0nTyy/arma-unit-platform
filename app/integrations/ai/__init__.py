from app.integrations.ai.claude import ClaudeChatClient
from app.integrations.ai.client import AIChatClient, AIResponse, ToolCall

# Every chat client speaks the same interface: chat(messages, tools) -> AIResponse.
ChatClient = AIChatClient | ClaudeChatClient

__all__ = ["AIChatClient", "AIResponse", "ChatClient", "ClaudeChatClient", "ToolCall"]
