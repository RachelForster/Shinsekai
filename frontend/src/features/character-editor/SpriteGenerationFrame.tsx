import { useEffect, useId, useRef, type ReactNode } from "react";
import { X } from "lucide-react";

import { useI18n } from "../../shared/i18n";
import { IconButton } from "../../shared/ui";

interface SpriteGenerationPageFrameProps {
  busy: boolean;
  characterName: string;
  children: ReactNode;
  footer: ReactNode;
  headerActions: ReactNode;
  modeTabs: ReactNode;
  onClose: () => void;
  title: string;
}

export function SpriteGenerationPageFrame({
  busy,
  characterName,
  children,
  footer,
  headerActions,
  modeTabs,
  onClose,
  title,
}: SpriteGenerationPageFrameProps) {
  const { t } = useI18n();
  const titleId = useId();
  const titleRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    titleRef.current?.focus();
  }, []);

  return (
    <div className="sprite-generation-screen">
      <section className="page sprite-generation" aria-labelledby={titleId}>
        <header className="sprite-generation__header">
          <div className="sprite-generation__heading">
            <h1 id={titleId} ref={titleRef} tabIndex={-1}>
              {title}
            </h1>
            <span className="sprite-generation__character-name" title={characterName}>
              {characterName}
            </span>
          </div>
          {modeTabs}
          <div className="sprite-generation__header-actions">
            {headerActions}
            <IconButton disabled={busy} label={t("common.close")} onClick={onClose}>
              <X aria-hidden className="icon-button__icon" />
            </IconButton>
          </div>
        </header>
        <div className="sprite-generation__body">{children}</div>
        <footer className="sprite-generation__footer">{footer}</footer>
      </section>
    </div>
  );
}
