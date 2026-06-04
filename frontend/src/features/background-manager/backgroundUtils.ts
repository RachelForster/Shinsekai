import type { Background } from "../../entities/config/types";
import type { MessageKey } from "../../shared/i18n";

export type BackgroundDeleteTarget =
  | { kind: "background"; name: string }
  | { filename: string; index: number; kind: "image"; name: string }
  | { count: number; kind: "all-images"; name: string }
  | { filename: string; index: number; kind: "bgm"; name: string }
  | { count: number; indexes: number[]; kind: "selected-bgm"; name: string }
  | { count: number; kind: "all-bgm"; name: string };

export type BgmSortDirection = "asc" | "desc";
export type BgmSortKey = "filename" | "index";

export interface BackgroundBgmItem {
  filename: string;
  originalIndex: number;
  path: string;
}

export interface BackgroundDeleteDialogCopy {
  body: string;
  confirmLabel: string;
  title: string;
}

interface BackgroundDeleteActions {
  deleteAllBgm: (name: string) => void;
  deleteAllImages: (name: string) => void;
  deleteBackground: (name: string) => void;
  deleteBgm: (target: { index: number; name: string }) => void;
  deleteImage: (target: { index: number; name: string }) => void;
  deleteSelectedBgm: (target: { indexes: number[]; name: string }) => void;
}

type BackgroundTranslate = (key: MessageKey, values?: Record<string, number | string>) => string;

export function createBackground(): Background {
  return {
    bg_tags: "",
    bgm_list: [],
    bgm_tags: "",
    name: "",
    sprite_prefix: "temp",
    sprites: [],
  };
}

export function backgroundDeleteDialogCopy(
  target: BackgroundDeleteTarget,
  t: BackgroundTranslate,
): BackgroundDeleteDialogCopy {
  switch (target.kind) {
    case "background":
      return {
        body: t("background.delete.confirmBody", { name: target.name }),
        confirmLabel: t("common.delete"),
        title: t("background.delete.confirmTitle"),
      };
    case "image":
      return {
        body: t("background.asset.deleteImageConfirmBody", {
          filename: target.filename,
          index: target.index + 1,
          name: target.name,
        }),
        confirmLabel: t("common.remove"),
        title: t("common.remove"),
      };
    case "all-images":
      return {
        body: t("background.asset.clearImagesConfirmBody", { count: target.count, name: target.name }),
        confirmLabel: t("common.delete"),
        title: t("background.asset.clearImages"),
      };
    case "bgm":
      return {
        body: t("background.asset.deleteBgmConfirmBody", {
          filename: target.filename,
          index: target.index + 1,
          name: target.name,
        }),
        confirmLabel: t("common.remove"),
        title: t("common.remove"),
      };
    case "selected-bgm":
      return {
        body: t("background.asset.deleteSelectedBgmConfirmBody", { count: target.count, name: target.name }),
        confirmLabel: t("common.delete"),
        title: t("background.asset.deleteSelectedBgm"),
      };
    case "all-bgm":
      return {
        body: t("background.asset.clearBgmConfirmBody", { count: target.count, name: target.name }),
        confirmLabel: t("common.delete"),
        title: t("background.asset.clearBgm"),
      };
  }
}

export function runBackgroundDeleteTarget(target: BackgroundDeleteTarget, actions: BackgroundDeleteActions) {
  switch (target.kind) {
    case "background":
      actions.deleteBackground(target.name);
      return;
    case "image":
      actions.deleteImage({ index: target.index, name: target.name });
      return;
    case "all-images":
      actions.deleteAllImages(target.name);
      return;
    case "bgm":
      actions.deleteBgm({ index: target.index, name: target.name });
      return;
    case "selected-bgm":
      actions.deleteSelectedBgm({ indexes: target.indexes, name: target.name });
      return;
    case "all-bgm":
      actions.deleteAllBgm(target.name);
      return;
  }
}
