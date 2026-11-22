"""Per-turn background scene context provider."""

from __future__ import annotations

from application.chat.capabilities.contracts import (
    BaseTurnContextProvider,
    TurnAdmissionRequest,
    TurnUserPromptContribution,
)
from application.chat.runtime.background_prompt import current_background_context


class BackgroundTurnContextProvider(BaseTurnContextProvider):
    """Resolve the active stage background for each turn without coupling `LLMWorker`."""

    capability_id = "background"

    def contribute_user_prompt(
        self,
        request: TurnAdmissionRequest,
    ) -> TurnUserPromptContribution | None:
        if request.runtime is None:
            return None
        background = current_background_context(request.runtime)
        if not background:
            return None
        return TurnUserPromptContribution(background=background)
