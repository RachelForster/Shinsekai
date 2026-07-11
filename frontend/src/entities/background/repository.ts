import { getPlatform } from "../../shared/platform/platform";
import type { BackgroundTranslateInput } from "../../shared/platform/types";
import type { Background } from "../config/types";

export const backgroundsQueryKey = ["backgrounds"] as const;

export function listBackgrounds() {
  return getPlatform().backgrounds.list();
}

export function saveBackground(background: Background, originalName?: string) {
  return getPlatform().backgrounds.save(background, originalName);
}

export function saveBackgroundImageTags(input: { bgTags: string; name: string }) {
  return getPlatform().backgrounds.saveImageTags(input);
}

export function saveBackgroundBgmTags(input: { bgmTags: string; name: string }) {
  return getPlatform().backgrounds.saveBgmTags(input);
}

export function deleteBackground(name: string) {
  return getPlatform().backgrounds.delete(name);
}

export function deleteBackgroundImage(name: string, index: number) {
  return getPlatform().backgrounds.deleteImage(name, index);
}

export function deleteAllBackgroundImages(name: string) {
  return getPlatform().backgrounds.deleteAllImages(name);
}

export function deleteBackgroundBgm(name: string, index: number) {
  return getPlatform().backgrounds.deleteBgm(name, index);
}

export function deleteAllBackgroundBgm(name: string) {
  return getPlatform().backgrounds.deleteAllBgm(name);
}

export function importBackgrounds(items: File[] | string[]) {
  return getPlatform().backgrounds.import(items);
}

export function exportBackground(name: string) {
  return getPlatform().backgrounds.export(name);
}

export function translateBackgroundFields(input: BackgroundTranslateInput) {
  return getPlatform().backgrounds.translateFields(input);
}

export function uploadBackgroundImages(input: { bgTags: string; name: string; paths: string[] }) {
  return getPlatform().backgrounds.uploadImages(input);
}

export function autoLabelBackgroundImages(name: string) {
  return getPlatform().backgrounds.autoLabelImages(name);
}

export function uploadBackgroundBgm(input: { bgmTags: string; name: string; paths: string[] }) {
  return getPlatform().backgrounds.uploadBgm(input);
}
