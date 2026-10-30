import { useI18n } from "../i18n";
import "./ComfyUIConnectionGuide.css";

/** Shared setup sequence for API settings and sprite generation. */
export function ComfyUIConnectionGuide() {
  const { t } = useI18n();
  const steps = [
    ["comfyGuide.startTitle", "comfyGuide.start"],
    ["comfyGuide.workflowTitle", "comfyGuide.workflow"],
    ["comfyGuide.exportTitle", "comfyGuide.export"],
    ["comfyGuide.connectTitle", "comfyGuide.connect"],
  ] as const;

  return (
    <ol className="comfy-connection-guide">
      {steps.map(([title, body]) => (
        <li key={title}>
          <strong>{t(title)}</strong>
          <p>{t(body)}</p>
        </li>
      ))}
    </ol>
  );
}
