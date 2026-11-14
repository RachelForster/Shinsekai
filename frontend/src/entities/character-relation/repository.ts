import { getPlatform } from "../../shared/platform/platform";
import type { RelationRequest } from "../../shared/platform/types";

export const relationQueryKey = ["character-relations"] as const;

export function getCharacterRelationGraph(owner: string) {
  return getPlatform().characterRelation.getRelationGraph(owner);
}

export function applyCharacterRelationChanges(owner: string, operations: RelationRequest[]) {
  return getPlatform().characterRelation.applyRelationChanges(owner, operations);
}
