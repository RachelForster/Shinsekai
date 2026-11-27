import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { getNovelDocument } from "../../../entities/novel/repository";
import { useI18n } from "../../../shared/i18n";
import { formatPlatformError } from "../../../shared/platform/errors";
import type { ChatBehaviorState, NovelChapterTocEntry } from "../../../shared/platform/types";
import { IconButton } from "../../../shared/ui";
import "./NovelChapterDrawer.css";

interface NovelHudView {
  docId: string;
  title: string;
  chapterIndex: number;
  totalChapters: number;
  chunkIndex: number;
  totalChunks: number;
  phase: string;
  chapters: NovelChapterTocEntry[];
  chaptersTruncated: boolean;
}

export function parseNovelHud(behavior?: ChatBehaviorState | null): NovelHudView | null {
  if (!behavior || behavior.behaviorId !== "novel_theater") return null;
  const hud = (behavior.hud ?? {}) as Record<string, unknown>;
  const totalChapters = Math.max(1, Number(hud.totalChapters ?? 1) || 1);
  const totalChunks = Math.max(1, Number(hud.totalChunks ?? 1) || 1);
  const rawChapters = Array.isArray(hud.chapters) ? (hud.chapters as NovelChapterTocEntry[]) : [];
  return {
    docId: typeof hud.docId === "string" ? hud.docId : "",
    title: typeof hud.title === "string" ? hud.title : "",
    chapterIndex: Math.max(0, Number(hud.chapterIndex ?? 0) || 0),
    totalChapters,
    chunkIndex: Math.max(0, Number(hud.chunkIndex ?? 0) || 0),
    totalChunks,
    phase: typeof hud.phase === "string" ? hud.phase : "ready",
    chapters: rawChapters,
    chaptersTruncated: Boolean(hud.chaptersTruncated),
  };
}

export function NovelChapterDrawer({
  open,
  behavior,
  onClose,
  onSelectChapter,
}: {
  open: boolean;
  behavior: ChatBehaviorState;
  onClose: () => void;
  onSelectChapter: (chapterIndex: number) => void;
}) {
  const { t } = useI18n();
  const hud = parseNovelHud(behavior);
  const [fullChaptersByDoc, setFullChaptersByDoc] = useState<Record<string, NovelChapterTocEntry[]>>({});
  const [loadingFull, setLoadingFull] = useState(false);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    if (!open || !hud?.chaptersTruncated || !hud.docId || fullChaptersByDoc[hud.docId]) {
      return;
    }
    let active = true;
    setLoadingFull(true);
    setLoadError("");
    void getNovelDocument(hud.docId)
      .then((detail) => {
        if (!active) return;
        setFullChaptersByDoc((prev) => ({ ...prev, [hud.docId]: detail.chapters ?? [] }));
      })
      .catch((error) => {
        if (!active) return;
        setLoadError(formatPlatformError(error, t));
      })
      .finally(() => {
        if (active) setLoadingFull(false);
      });
    return () => {
      active = false;
    };
  }, [fullChaptersByDoc, hud?.chaptersTruncated, hud?.docId, open, t]);

  if (!open || !hud) return null;

  const chapters = fullChaptersByDoc[hud.docId] ?? hud.chapters;
  const progressText = t("novel.drawer.progress", {
    chapter: Math.min(hud.chapterIndex + 1, hud.totalChapters),
    current: Math.min(hud.chunkIndex + 1, hud.totalChunks),
    total: hud.totalChunks,
  });

  return (
    <div
      className="novel-chapter-drawer__backdrop"
      data-chat-stage-hitbox="true"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside aria-label={t("novel.drawer.title")} className="novel-chapter-drawer" role="dialog">
        <header className="novel-chapter-drawer__header">
          <h2>{t("novel.drawer.title")}</h2>
          <IconButton label={t("common.close")} onClick={onClose}>
            <X aria-hidden className="icon-button__icon" />
          </IconButton>
        </header>
        <div className="novel-chapter-drawer__meta">
          {hud.title ? <div className="novel-chapter-drawer__book">{hud.title}</div> : null}
          <div className="novel-chapter-drawer__progress">{progressText}</div>
          {hud.phase === "generating" ? (
            <p className="novel-chapter-drawer__status" role="status">
              {t("novel.drawer.phase.generating")}
            </p>
          ) : null}
          {hud.phase === "ended" ? (
            <p className="novel-chapter-drawer__status" role="status">
              {t("novel.drawer.phase.ended")}
            </p>
          ) : null}
        </div>
        <div className="novel-chapter-drawer__list">
          {loadingFull ? (
            <p className="novel-chapter-drawer__status" role="status">
              {t("novel.drawer.loading")}
            </p>
          ) : null}
          {loadError ? (
            <p className="story-generator-error" role="alert">
              {loadError}
            </p>
          ) : null}
          {!loadingFull && chapters.length === 0 ? (
            <p className="novel-chapter-drawer__status">{t("novel.drawer.empty")}</p>
          ) : (
            chapters.map((chapter) => {
              const isCurrent = chapter.index === hud.chapterIndex;
              const startBeat = chapter.startChunkIndex + 1;
              const endBeat = Math.max(startBeat, chapter.startChunkIndex + Math.max(1, chapter.chunkCount));
              return (
                <button
                  className="novel-chapter-drawer__item"
                  data-current={isCurrent ? "true" : undefined}
                  key={`chapter-${chapter.index}`}
                  onClick={() => onSelectChapter(chapter.index)}
                  type="button"
                >
                  <span className="novel-chapter-drawer__item-title">{chapter.title}</span>
                  <span className="novel-chapter-drawer__item-side">
                    <span>{t("novel.drawer.chapterRange", { start: startBeat, end: endBeat })}</span>
                    {isCurrent ? (
                      <span className="novel-chapter-drawer__current-tag">{t("novel.drawer.current")}</span>
                    ) : null}
                  </span>
                </button>
              );
            })
          )}
        </div>
      </aside>
    </div>
  );
}
