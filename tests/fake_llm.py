"""A scripted chat model with tool calling, for offline tests of the LangGraph agents (HW7)."""

from typing import Any, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedToolModel(BaseChatModel):
    """Plays back replies: a string is a final answer, a list of (tool, args) is tool calls."""

    replies: List[Any]
    i: int = 0
    seen: List[Any] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.seen.append(list(messages))
        reply = self.replies[min(self.i, len(self.replies) - 1)]
        self.i += 1
        if isinstance(reply, str):
            message = AIMessage(content=reply)
        else:
            calls = [
                {"name": n, "args": a, "id": f"call{self.i}_{k}"} for k, (n, a) in enumerate(reply)
            ]
            message = AIMessage(content="", tool_calls=calls)
        return ChatResult(generations=[ChatGeneration(message=message)])
