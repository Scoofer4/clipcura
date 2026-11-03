"""Built-in assistant on an Ollama server (#27)."""
from clipcura.assistant import ollama
from clipcura.assistant.chat import Assistant, AssistantBusy, Conversation, explain_prompt
from clipcura.assistant.ollama import OllamaError

__all__ = ["Assistant", "AssistantBusy", "Conversation", "OllamaError", "explain_prompt", "ollama"]
