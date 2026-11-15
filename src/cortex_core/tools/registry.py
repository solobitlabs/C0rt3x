"""Registro tipado de ferramentas executaveis pelo Fast-Path e pelo LLM."""

from dataclasses import dataclass
import inspect
from typing import Any, Awaitable, Callable, Dict, List


ToolHandler = Callable[..., Any] | Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class RegisteredTool:
    """Metadados e handler de uma ferramenta registrada."""

    name: str
    description: str
    handler: ToolHandler


class ToolRegistry:
    """Catalogo central de ferramentas com validacao e isolamento."""

    def __init__(self) -> None:
        self._tools: Dict[str, RegisteredTool] = {}

    def register(self, name: str, description: str, handler: ToolHandler) -> None:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Nome da ferramenta nao pode ser vazio")
        self._tools[clean_name] = RegisteredTool(
            name=clean_name,
            description=description.strip(),
            handler=handler,
        )

    def list_tools(self) -> List[Dict[str, str]]:
        return [
            {"name": t.name, "description": t.description}
            for t in sorted(self._tools.values(), key=lambda x: x.name)
        ]

    async def execute(self, name: str, **kwargs: Any) -> Any:
        tool = self._tools.get(name)
        if not tool:
            raise KeyError(f"Ferramenta nao registrada: {name}")
        result = tool.handler(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result
