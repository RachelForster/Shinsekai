import { useI18n } from "../../shared/i18n";
import type { SpriteMatting } from "../../shared/platform/types";

export function SpriteMattingStatus({ matting }: { matting?: SpriteMatting }) {
  const { t } = useI18n();
  if (!matting) return null;
  const color = matting.screenColor ? `rgb(${matting.screenColor.join(",")})` : undefined;
  return (
    <p className="sprite-generation__hint">
      {color ? (
        <span className="sprite-generation__screen-color" style={{ backgroundColor: color }} aria-hidden="true" />
      ) : null}
      {t(matting.method === "chroma" ? "spriteMatting.chroma" : "spriteMatting.ai")}
      {matting.alphaMatting ? ` · ${t("spriteMatting.alpha")}` : ""}
      {matting.reason === "opaque-reference" ? ` · ${t("spriteMatting.opaque")}` : ""}
      {matting.reason === "foreground-colors" ? ` · ${t("spriteMatting.palette")}` : ""}
    </p>
  );
}
