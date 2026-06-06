import { NavLink } from "react-router-dom";
import { Cpu, ImagePlus, Sparkles } from "lucide-react";

import { useI18n } from "../../shared/i18n";

interface CharacterAiSpriteCardProps {
  characterName: string;
}

export function CharacterAiSpriteCard({ characterName }: CharacterAiSpriteCardProps) {
  const { t } = useI18n();
  const trimmedName = characterName.trim();
  const target = `/settings/ai-sprites${trimmedName ? `?character=${encodeURIComponent(trimmedName)}` : ""}`;

  return (
    <section className="character-ai-sprite-card" aria-label={t("character.aiSprites.cardTitle")}>
      <div className="character-ai-sprite-card__visual" aria-hidden>
        <Sparkles className="character-ai-sprite-card__spark" />
        <div className="character-ai-sprite-card__scan" />
      </div>
      <div className="character-ai-sprite-card__copy">
        <span className="character-ai-sprite-card__eyebrow">
          <Cpu aria-hidden />
          {t("character.aiSprites.cardEyebrow")}
        </span>
        <h2>{t("character.aiSprites.cardTitle")}</h2>
        <p>{t("character.aiSprites.cardBody")}</p>
      </div>
      <NavLink className="button button--primary character-ai-sprite-card__action" to={target}>
        <ImagePlus aria-hidden className="button__icon" />
        <span className="button__label">{t("character.aiSprites.cardAction")}</span>
      </NavLink>
    </section>
  );
}
