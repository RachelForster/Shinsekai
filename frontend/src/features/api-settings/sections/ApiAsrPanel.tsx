import type { PageSectionProps } from "../../../shared/ui";
import { AsrSettingsSection } from "../AsrSettingsSection";
import type { ApiSettingsPageContext } from "../apiSettingsContext";
import { useApiAsrController } from "../controllers/useApiAsrController";

export function ApiAsrPanel({ ctx, id }: PageSectionProps<ApiSettingsPageContext>) {
  const asr = useApiAsrController(ctx);

  return (
    <AsrSettingsSection
      activeAsrProvider={asr.activeAsrProvider}
      activeAsrSchema={asr.activeAsrSchema}
      asrComputeSelectOptions={asr.asrComputeSelectOptions}
      asrProviderSelectOptions={asr.asrProviderSelectOptions}
      currentAsrCompute={asr.currentAsrCompute}
      customWhisperModel={asr.customWhisperModel}
      disabled={ctx.savePending}
      draft={ctx.draft}
      id={id}
      onAsrExtraChange={asr.updateAsrExtra}
      onPersistSystemDraft={ctx.persistSystemDraftForModel}
      onSystemPatch={ctx.updateSystemDraft}
      showWhisperFields={asr.showWhisperFields}
      systemDraft={ctx.systemDraft}
      voskModelPath={asr.voskModelPath}
      whisperPresetValue={asr.whisperPresetValue}
    />
  );
}
