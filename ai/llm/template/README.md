# Composite prompt templates

`Section` is both the base node and a composite. Each node has an `id`, a
`priority`, boolean `enabled` (default `True`), child `children`, and
`render(context) -> str`. Lower priorities
render first; equal priorities retain insertion order. IDs must be nonempty
and unique among siblings. A parent renders its own content, then its children.
Empty output is omitted; nonempty text and whitespace are preserved.
Setting `enabled=False` skips the node's content, context hooks and entire
subtree. The flag is keyword-only to preserve existing positional constructors.

`TemplateContext` is a frozen dataclass base with no prescribed business fields.
Subclasses define the data needed by their sections. By default, a parent passes
the same context object to every child. Override `context_for_children` and use
`dataclasses.replace` for a subtree-specific context; sibling contexts are not
changed. Override `children_for_context` when a section's children depend on the
current request. The core renderer still validates, orders and renders those
children. Sections do not retain context or rendered text between requests.

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

`dialog.DialogTemplateSection` is the root and directly owns four major
sections, each defined in its own file:

```text
DialogTemplateSection             sections/dialog_template.py
  JsonSchemaSection               sections/json_schema.py
  CharacterSection                sections/character.py
  BackgroundSection               sections/background.py
  RequirementsSection             sections/requirements.py
```

The root renders the preamble, then its four children in priority order.
`JsonSchemaSection` owns the JSON example and patched field contract;
`CharacterSection` owns sprites and character profiles; `BackgroundSection`
owns scene and music catalogs; `RequirementsSection` owns tool guidance,
patched rules, closing text and the final JSON reminder. Small text nodes
within each section use `enabled` for optional content. Context-dependent child
nodes are returned by `children_for_context`, so callers can inspect the same
Composite nodes that the renderer uses.

All five classes are exported from `ai.llm.template.dialog` and can be
constructed without arguments. Customize `root.children` with
`dataclasses.replace` to disable, reorder or replace a major section.
`build_dialog_section()` remains a compatibility factory returning the named root.

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

`dialog/sections/requirements.py` declares all rule nodes with their priorities
and `enabled` values. Disabled features remain visible in the node list and do
not render or translate their rule text. Localized arguments and the SDK patch
bridge live under `dialog/contracts/`; the renderable rule leaf is
`dialog/sections/requirement.py`.
The bridge preserves the old distinction: a patch to an unavailable feature's
rule is a no-op, while `add_requirements` may explicitly introduce that rule.

`dialog/contracts/patches.py` applies the existing SDK `OutputContractPatch`
objects to output fields and requirements. Patch priority is ascending and ties
preserve input order, independently of section ordering. Each render starts from
fresh base fields and requirements; patches are never accumulated in the context.

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
  dialog/               # Dialog prompt domain
    context.py
    sections/            # Composite nodes; one Section subclass per file
      dialog_template.py
      json_schema.py
      character.py
      background.py
      requirements.py
      requirement.py
    contracts/           # Output-contract construction and patch adapters
      arguments.py
      fields.py
      requirements.py
      patches.py
  prompts/              # System and user text assembly
    system.py
    user.py
  integrations/         # Application configuration and external registries
    characters.py
    localization.py
    tools.py
```

Each subpackage has an `__init__.py`. The `template` package exports the core
primitives, `dialog` exports its context and named sections, and `prompts` exports its
contexts and builders. The existing facade remains at
`ai/llm/template_generator.py`. `integrations` does not eagerly import adapters,
so importing the core or prompt builders does not initialize tool registries.

Run `python -m pytest test/unit/ai/llm/template test/unit/sdk/test_output_contracts.py
test/unit/application/test_chat_templates.py`. The compatibility fixture digests
were captured from the original renderer at `d8677c71`, before replacement, for
all 128 combinations of the seven feature flags in Chinese, English and Japanese.
They also exercise voice-language suppression, background aliases, character
deduplication and length limits. Do not regenerate them merely to accept a diff.
