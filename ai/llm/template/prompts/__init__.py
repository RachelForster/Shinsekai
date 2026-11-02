"""System and user text assembly using the shared Composite primitives."""

from .system import RuntimePromptContext, build_runtime_prompt_section
from .user import UserPromptContext, build_user_prompt_section

__all__ = [
    "RuntimePromptContext",
    "UserPromptContext",
    "build_runtime_prompt_section",
    "build_user_prompt_section",
]
