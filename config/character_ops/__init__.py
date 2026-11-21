"""Cohesive character domain operations decoupled from persistence backends."""

from config.character_ops.groups import save_character_sprite_groups
from config.character_ops.profile import (
    clamp_portrait_sprite_index,
    delete_character_and_assets,
    resolve_mutable_character,
    save_character_emotion_tags_op,
    save_character_patch,
    save_character_sprite_scale_op,
)
from config.character_ops.relations import (
    parse_relation_graph,
    rename_relation_graph_owner,
    update_character_relation_graph,
)
from config.character_ops.sprites import (
    delete_all_character_sprites,
    delete_single_character_sprite,
    save_character_avatar_bank,
    save_character_sprite_mouths,
    save_character_sprite_transitions,
    upload_character_sprites,
)
from config.character_ops.target import (
    CharacterPersistenceTarget,
    CharacterProfileError,
    ConfigManagerCharacterTarget,
)
from config.character_ops.voices import (
    delete_character_sprite_voice,
    get_character_sprite_voice,
    save_character_sprite_voice_text,
    save_character_sprite_voice_type,
    upload_character_sprite_voice,
    voice_filename_for_sprite,
)

__all__ = [
    "CharacterPersistenceTarget",
    "CharacterProfileError",
    "ConfigManagerCharacterTarget",
    "clamp_portrait_sprite_index",
    "delete_all_character_sprites",
    "delete_character_and_assets",
    "delete_character_sprite_voice",
    "delete_single_character_sprite",
    "get_character_sprite_voice",
    "parse_relation_graph",
    "rename_relation_graph_owner",
    "resolve_mutable_character",
    "save_character_avatar_bank",
    "save_character_emotion_tags_op",
    "save_character_patch",
    "save_character_sprite_groups",
    "save_character_sprite_mouths",
    "save_character_sprite_scale_op",
    "save_character_sprite_transitions",
    "save_character_sprite_voice_text",
    "save_character_sprite_voice_type",
    "update_character_relation_graph",
    "upload_character_sprite_voice",
    "upload_character_sprites",
    "voice_filename_for_sprite",
]
