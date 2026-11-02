import { getPlatform } from "../../shared/platform/platform";
import type { Effect } from "../config/types";

export const effectsQueryKey = ["effects"] as const;

export function listEffects() {
  return getPlatform().effects.list();
}

export function saveEffect(effect: Effect, originalName?: string) {
  return getPlatform().effects.save(effect, originalName);
}

export function saveEffectAudioTags(input: { audioTags: string; name: string }) {
  return getPlatform().effects.saveAudioTags(input);
}

export function deleteEffect(name: string) {
  return getPlatform().effects.delete(name);
}

export function deleteEffectAudio(name: string, index: number) {
  return getPlatform().effects.deleteAudio(name, index);
}

export function deleteEffectImage(name: string, index: number) {
  return getPlatform().effects.deleteImage(name, index);
}

export function deleteAllEffectAudio(name: string) {
  return getPlatform().effects.deleteAllAudio(name);
}

export function importEffects(items: File[] | string[]) {
  return getPlatform().effects.import(items);
}

export function exportEffect(name: string) {
  return getPlatform().effects.export(name);
}

export function uploadEffectAudio(input: { audioTags: string; name: string; paths: string[] }) {
  return getPlatform().effects.uploadAudio(input);
}

export function saveEffectImageTags(input: { imageTags: string; name: string }) {
  return getPlatform().effects.saveImageTags(input);
}

export function uploadEffectImages(input: { imageTags: string; name: string; paths: string[] }) {
  return getPlatform().effects.uploadImages(input);
}

export function uploadEffectImageAudio(input: { index: number; name: string; path: string }) {
  return getPlatform().effects.uploadImageAudio(input);
}
