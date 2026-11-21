"""Reminder constraints composed with the normal dialog output contract."""

import json
from dataclasses import dataclass
from typing import Mapping

from ai.llm.template.core import (
    I18nSection,
    PromptSpec,
    Section,
    TemplateContext,
    TextSection,
)
from ai.llm.template.dialog import DialogTemplateContext, DialogTemplateSection


@dataclass(frozen=True)
class ReminderContext(TemplateContext):
    payload: Mapping[str, str | int]
    dialog: DialogTemplateContext


def build_reminder_system_section() -> Section[ReminderContext]:
    return Section(
        id="reminder.system",
        separator="\n",
        children=(
            TextSection(
                "dialog",
                text=lambda context: DialogTemplateSection().render(context.dialog),
            ),
            I18nSection(
                "reminder",
                key="session.reminder_system",
            ),
        ),
    )


def build_reminder_user_section() -> Section[ReminderContext]:
    return Section(
        id="reminder.user",
        children=(
            TextSection(
                "request",
                text=lambda context: json.dumps(context.payload, ensure_ascii=False),
            ),
        ),
    )


REMINDER_PROMPT_SPEC = PromptSpec(
    id="session.reminder",
    system_builder=build_reminder_system_section,
    user_builder=build_reminder_user_section,
)
