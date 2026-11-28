import {
  findSelfPersona,
  isSelfPersonaId,
  isSelfPersonaName,
  SELF_PERSONA_ID,
  SELF_PERSONA_NAME,
  SELF_PERSONA_SPRITE_PREFIX,
} from "../../../playerCharacterOptions";
import type { Character, RelationGraph } from "../../slices/characterTypes";
import type { ChatLaunchPayload } from "../../slices/chatTypes";
import type { SystemConfig } from "../../slices/configTypes";
import type { Background, TemplateLaunchSession } from "../../slices/workspaceTypes";
import { generateStandaloneTemplateSummary } from "../ai/templateGenerator";
import type { StandaloneSessionRecord } from "./sessionStore";

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

function rewriteNameList(items: string[], oldCf: string, newName: string): { next: string[]; changed: boolean } {
  const next = items.map((name) => replaceName(name, oldCf, newName));
  const changed = next.some((name, idx) => name !== items[idx]);
  return { next, changed };
}

function templateSessionReferencesName(session: TemplateLaunchSession, targetCf: string): boolean {
  if (session.playerCharacter && session.playerCharacter.trim().toLowerCase() === targetCf) {
    return true;
  }
  if (session.selectedCharacters.some((name) => name.trim().toLowerCase() === targetCf)) {
    return true;
  }
  return Boolean(session.primaryCharacters?.some((name) => name.trim().toLowerCase() === targetCf));
}

export interface StandaloneRenameCascadeInput {
  oldName: string;
  newName: string;
  isSelf: boolean;
  characters: Character[];
  backgrounds: Background[];
  systemConfig: SystemConfig;
  templateSession: TemplateLaunchSession | null;
  sessions: StandaloneSessionRecord[];
}

export function cascadeStandaloneCharacterRename(input: StandaloneRenameCascadeInput): {
  templateSessionChanged: boolean;
  updatedSessions: StandaloneSessionRecord[];
} {
  const oldCf = input.oldName.trim().toLowerCase();
  const newCf = input.newName.trim().toLowerCase();
  if (!oldCf || !newCf || oldCf === newCf) {
    return { templateSessionChanged: false, updatedSessions: [] };
  }

  let templateSessionChanged = false;
  const session = input.templateSession;
  if (session) {
    let refsChanged = false;
    if (session.playerCharacter && session.playerCharacter.trim().toLowerCase() === oldCf) {
      session.playerCharacter = input.newName;
      refsChanged = true;
    }
    const sel = rewriteNameList(session.selectedCharacters, oldCf, input.newName);
    if (sel.changed) {
      session.selectedCharacters = sel.next;
      refsChanged = true;
    }
    if (session.primaryCharacters) {
      const prim = rewriteNameList(session.primaryCharacters, oldCf, input.newName);
      if (prim.changed) {
        session.primaryCharacters = prim.next;
        refsChanged = true;
      }
    }
    if (refsChanged) {
      templateSessionChanged = true;
    }

    const referencesTarget =
      refsChanged || templateSessionReferencesName(session, oldCf) || templateSessionReferencesName(session, newCf);
    if (
      (referencesTarget || input.isSelf) &&
      !session.systemManuallyEdited &&
      session.selectedCharacters.length > 0 &&
      (session.system ?? "").trim()
    ) {
      try {
        const generated = generateStandaloneTemplateSummary(
          {
            name: session.filenameStub || "session",
            characters: session.selectedCharacters,
            primaryCharacters: session.primaryCharacters,
            characterPromptMode: session.characterPromptMode,
            backgroundName: session.background,
            effectNames: session.effectNames,
            mediaSelectionMode: session.mediaSelectionMode,
            playerCharacter: session.playerCharacter,
            readPlayerSpeech: session.readPlayerSpeech,
            allowPlayerDialogue: session.allowPlayerDialogue,
            maxDialogItems: session.maxDialogItems,
            maxSpeechChars: session.maxSpeechChars,
            useCg: session.useCg,
            useChoice: session.useChoice,
            useCot: session.useCot,
            useEffect: session.useEffect,
            useNarration: session.useNarration,
            useStat: session.useStat,
            useTranslation: session.useTranslation,
            voiceLanguage: session.voiceLanguage,
            scenario: session.scenario,
          },
          {
            characters: input.characters,
            background_list: input.backgrounds,
            system_config: input.systemConfig,
          },
        );
        const nextSystem = generated.system ?? "";
        if (nextSystem && nextSystem !== session.system) {
          session.system = nextSystem;
          templateSessionChanged = true;
        }
      } catch {
        // Keep existing system text if cast resolution is temporarily incomplete.
      }
    }
  }

  const updatedSessions: StandaloneSessionRecord[] = [];
  for (const record of input.sessions) {
    let changed = false;
    let refsTouched = false;
    const nextRecord: StandaloneSessionRecord = structuredClone(record);

    const recordChars = rewriteNameList(nextRecord.characters, oldCf, input.newName);
    if (recordChars.changed) {
      nextRecord.characters = recordChars.next;
      changed = true;
      refsTouched = true;
    }
    const recordPrimary = rewriteNameList(nextRecord.primaryCharacters, oldCf, input.newName);
    if (recordPrimary.changed) {
      nextRecord.primaryCharacters = recordPrimary.next;
      changed = true;
      refsTouched = true;
    }

    const nextPayload: ChatLaunchPayload = nextRecord.payload;
    if (nextPayload.playerCharacter && nextPayload.playerCharacter.trim().toLowerCase() === oldCf) {
      nextPayload.playerCharacter = input.newName;
      changed = true;
      refsTouched = true;
    }
    const payloadChars = rewriteNameList(nextPayload.characters, oldCf, input.newName);
    if (payloadChars.changed) {
      nextPayload.characters = payloadChars.next;
      changed = true;
      refsTouched = true;
    }
    if (nextPayload.primaryCharacters) {
      const payloadPrimary = rewriteNameList(nextPayload.primaryCharacters, oldCf, input.newName);
      if (payloadPrimary.changed) {
        nextPayload.primaryCharacters = payloadPrimary.next;
        changed = true;
        refsTouched = true;
      }
    }

    const editor = nextPayload.editorSession;
    if (editor) {
      if (editor.playerCharacter && editor.playerCharacter.trim().toLowerCase() === oldCf) {
        editor.playerCharacter = input.newName;
        changed = true;
        refsTouched = true;
      }
      const editorSel = rewriteNameList(editor.selectedCharacters, oldCf, input.newName);
      if (editorSel.changed) {
        editor.selectedCharacters = editorSel.next;
        changed = true;
        refsTouched = true;
      }
      if (editor.primaryCharacters) {
        const editorPrim = rewriteNameList(editor.primaryCharacters, oldCf, input.newName);
        if (editorPrim.changed) {
          editor.primaryCharacters = editorPrim.next;
          changed = true;
          refsTouched = true;
        }
      }
    }

    const isStory = Boolean(nextPayload.storyPath);
    const isManual = Boolean(editor?.systemManuallyEdited);
    if ((refsTouched || input.isSelf) && !isStory && !isManual) {
      if (nextPayload.system) {
        nextPayload.system = "";
        changed = true;
      }
      if (editor?.system) {
        editor.system = "";
        changed = true;
      }
    }

    if (changed) {
      updatedSessions.push(nextRecord);
    }
  }

  return { templateSessionChanged, updatedSessions };
}

export function migrateStandaloneSelfPersonaDisplayName(
  characters: Character[],
  templateSession?: TemplateLaunchSession | null,
): { configChanged: boolean; templateSessionChanged: boolean; renamedFrom?: string; renamedTo?: string } {
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

  return {
    configChanged,
    templateSessionChanged,
    renamedFrom: oldName,
    renamedTo: legacyDisplayName,
  };
}
