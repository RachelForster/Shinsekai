import {
  findSelfPersona,
  isSelfPersonaId,
  isSelfPersonaName,
  SELF_PERSONA_ID,
  SELF_PERSONA_NAME,
  SELF_PERSONA_SPRITE_PREFIX,
} from "../../../playerCharacterOptions";
import type { Character, RelationGraph } from "../../slices/characterTypes";
import type { TemplateLaunchSession } from "../../slices/workspaceTypes";

function renameGraphReferences(
  graph: RelationGraph | undefined,
  oldName: string,
  newName: string,
): { graph: RelationGraph; changed: boolean } | null {
  if (!graph) return null;
  const oldCf = oldName.trim().toLowerCase();
  const newCf = newName.trim().toLowerCase();
  const nodes = graph.nodes ?? [];
  const hasOld = nodes.some((node) => node.key.trim().toLowerCase() === oldCf);
  const hasNew = nodes.some((node) => node.key.trim().toLowerCase() === newCf);
  if (!hasOld || hasNew) {
    return null;
  }
  const nextNodes = nodes.map((node) => (node.key.trim().toLowerCase() === oldCf ? { ...node, key: newName } : node));
  const nextEdges = (graph.edges ?? []).map((edge) => ({
    ...edge,
    source: edge.source.trim().toLowerCase() === oldCf ? newName : edge.source,
    target: edge.target.trim().toLowerCase() === oldCf ? newName : edge.target,
  }));
  return {
    graph: {
      ...graph,
      nodes: nextNodes,
      edges: nextEdges,
    },
    changed: true,
  };
}

function replaceName(value: string, oldCf: string, newName: string): string {
  return value.trim().toLowerCase() === oldCf ? newName : value;
}

export function migrateStandaloneSelfPersonaDisplayName(
  characters: Character[],
  templateSession?: TemplateLaunchSession | null,
): { configChanged: boolean; templateSessionChanged: boolean } {
  const selfChar = findSelfPersona(characters);
  if (!selfChar) {
    return { configChanged: false, templateSessionChanged: false };
  }

  let configChanged = false;
  if (!isSelfPersonaId(selfChar.id)) {
    selfChar.id = SELF_PERSONA_ID;
    configChanged = true;
  }
  if (!selfChar.is_builtin) {
    selfChar.is_builtin = true;
    configChanged = true;
  }
  if (!selfChar.pinned) {
    selfChar.pinned = true;
    configChanged = true;
  }
  if (!selfChar.undeletable) {
    selfChar.undeletable = true;
    configChanged = true;
  }
  if (!selfChar.sprite_prefix?.trim()) {
    selfChar.sprite_prefix = SELF_PERSONA_SPRITE_PREFIX;
    configChanged = true;
  }

  const currentName = selfChar.name.trim();
  const legacyDisplayName = selfChar.display_name?.trim() ?? "";
  if (
    !isSelfPersonaName(currentName) ||
    !legacyDisplayName ||
    legacyDisplayName.toLowerCase() === currentName.toLowerCase()
  ) {
    return { configChanged, templateSessionChanged: false };
  }

  const collision = characters.some(
    (char) => char !== selfChar && char.name.trim().toLowerCase() === legacyDisplayName.toLowerCase(),
  );
  if (collision) {
    return { configChanged, templateSessionChanged: false };
  }

  const oldName = currentName || SELF_PERSONA_NAME;
  const oldCf = oldName.toLowerCase();
  selfChar.name = legacyDisplayName;
  selfChar.display_name = "";
  configChanged = true;

  for (const char of characters) {
    const renamed = renameGraphReferences(char.relation_graph, oldName, legacyDisplayName);
    if (renamed?.changed) {
      char.relation_graph = renamed.graph;
    }
  }

  let templateSessionChanged = false;
  if (templateSession) {
    if (templateSession.playerCharacter && templateSession.playerCharacter.trim().toLowerCase() === oldCf) {
      templateSession.playerCharacter = legacyDisplayName;
      templateSessionChanged = true;
    }
    const nextSelected = templateSession.selectedCharacters.map((name) => replaceName(name, oldCf, legacyDisplayName));
    if (nextSelected.some((name, idx) => name !== templateSession.selectedCharacters[idx])) {
      templateSession.selectedCharacters = nextSelected;
      templateSessionChanged = true;
    }
    if (templateSession.primaryCharacters) {
      const nextPrimary = templateSession.primaryCharacters.map((name) => replaceName(name, oldCf, legacyDisplayName));
      if (nextPrimary.some((name, idx) => name !== templateSession.primaryCharacters![idx])) {
        templateSession.primaryCharacters = nextPrimary;
        templateSessionChanged = true;
      }
    }
  }

  return { configChanged, templateSessionChanged };
}
