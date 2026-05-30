import type { Background } from "../../entities/config/types";

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
