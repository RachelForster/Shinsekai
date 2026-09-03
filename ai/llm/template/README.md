# Composite prompt templates

`Section` is both the base node and a composite. Each node has an `id`, a
`priority`, child `children`, and `render(context) -> str`. Lower priorities
render first; equal priorities retain insertion order. IDs must be nonempty
and unique among siblings. A parent renders its own content, then its children.
Empty output is omitted; nonempty text and whitespace are preserved.

`TemplateContext` is a frozen dataclass base with no prescribed business fields.
Subclasses define the data needed by their sections. By default, a parent passes
the same context object to every child. Override `context_for_children` and use
`dataclasses.replace` for a subtree-specific context; sibling contexts are not
changed. Sections do not retain context or rendered text between requests.

## Custom sections and contexts

```python
from dataclasses import dataclass, replace
from ai.llm.template import Section, TemplateContext, TextSection

@dataclass(frozen=True)
class SceneContext(TemplateContext):
    speaker: str
    user_input: str

class SpeakerSection(Section[SceneContext]):
    def render_content(self, context: SceneContext) -> str:
        return f"Current speaker: {context.speaker}"

prompt = Section("system", separator="\n", children=(
    SpeakerSection("speaker", priority=10),
    TextSection("input", priority=20, text=lambda ctx: ctx.user_input),
))
context = SceneContext(speaker="Alice", user_input="Tell me about the town.")
text = prompt.render(context)
```

Override `render_content` to keep automatic child traversal and ordering.
`render` can also be overridden when a section needs complete rendering control.
Use `dataclasses.replace(prompt, children=(...))` to customize a tree; sections
and their child tuples are immutable. A `TextSection` accepts a literal string
or a callable receiving the current context. User text is never processed with
`str.format` or evaluated as template syntax.

## Dialog system prompts

`dialog.build_dialog_section()` builds this reusable tree:

```text
dialog.system
  preamble
  output
    example
    fields
  characters
    sprites
    profiles
  background
    scenes
    music
  tools
  requirements
  closing
  json_reminder
```

Render it with `dialog.DialogTemplateContext`. Character resources,
background, translation callback, tool text and patches are supplied explicitly.
The renderer does not load configuration, discover plugins or query tools.
The existing `ai.llm.template_generator.TemplateGenerator` remains the application
facade and resolves those dependencies. Its signature, error type, public helpers
and `(template, warning)` return value are unchanged.

## System and user prompt assembly

`prompts.build_runtime_prompt_section()` composes system rules, the user scenario,
then the JSON reminder. `application.chat.templates` retains its existing empty
scenario fallback and newline policy at the application boundary.

`prompts.build_user_prompt_section()` composes optional prefix context, literal
user input and optional suffix guidance. It is also used by the existing template
generation prompt assembly. For a chat input with retrieved memory:

```python
from ai.llm.template.prompts import UserPromptContext, build_user_prompt_section

text = build_user_prompt_section().render(UserPromptContext(
    prefix="Previously: Alice agreed to meet at the station.",
    user_input="Who is waiting for me?",
    suffix="Continue the scene.",
))
```

This API composes text only. Transport roles, attachments and message history
remain the responsibility of their existing callers.

## Patch compatibility

`dialog/patches.py` applies the existing SDK `OutputContractPatch` objects to output
fields and requirements. Patch priority is ascending and ties preserve input
order, independently of section ordering. Each render starts from fresh base
fields and requirements; patches are never accumulated in the context.

- Field removal cannot remove `character_name`, `speech` or `sprite`.
- Field overrides retain aliases; empty descriptions keep the existing text.
- Field additions follow overrides, retaining the existing overwrite semantics.
- Requirements retain stable IDs and append/prepend/replace/remove operations.
- Requirement additions can replace or re-enable an existing requirement.
- Unknown requirement modes log a warning and retain the existing requirement.
- JSON examples retain their existing behavior; patches affect field notes and
  requirements, not the illustrative JSON example.

## Files and verification

Files are grouped by responsibility:

```text
template/
  core/                 # Reusable Composite primitives
    context.py
    section.py
  dialog/               # Dialog system prompt and output-contract patches
    builder.py
    context.py
    catalogs.py
    fields.py
    requirements.py
    patches.py
  prompts/              # System and user text assembly
    composition.py
  integrations/         # Application configuration and external registries
    characters.py
    localization.py
    tools.py
```

Each subpackage has an `__init__.py`. The `template` package exports the core
primitives, `dialog` exports its context and builder, and `prompts` exports its
contexts and builders. The existing facade remains at
`ai/llm/template_generator.py`. `integrations` does not eagerly import adapters,
so importing the core or prompt builders does not initialize tool registries.

Run `python -m pytest test/unit/ai/llm/template test/unit/sdk/test_output_contracts.py
test/unit/application/test_chat_templates.py`. The compatibility fixture digests
were captured from the original renderer at `d8677c71`, before replacement, for
all 128 combinations of the seven feature flags in Chinese, English and Japanese.
They also exercise voice-language suppression, background aliases, character
deduplication and length limits. Do not regenerate them merely to accept a diff.
