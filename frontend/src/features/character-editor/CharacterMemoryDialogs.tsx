import { Button, Dialog, TaskProgress } from "../../shared/ui";
import { useI18n } from "../../shared/i18n";
import type { TaskSnapshot } from "../../shared/platform/types";

interface CharacterMemoryDialogsProps {
  depInstalling: boolean;
  dependencyOpen: boolean;
  dependencyTask: TaskSnapshot | null;
  loadingMessage: string;
  loadingOpen: boolean;
  loadingTask: TaskSnapshot | null;
  onCloseDependency: () => void;
  onCloseLoading: () => void;
}

export function CharacterMemoryDialogs({
  depInstalling,
  dependencyOpen,
  dependencyTask,
  loadingMessage,
  loadingOpen,
  loadingTask,
  onCloseDependency,
  onCloseLoading,
}: CharacterMemoryDialogsProps) {
  const { t } = useI18n();

  return (
    <>
      <Dialog
        closeLabel={t("common.close")}
        footer={
          depInstalling ? (
            <Button disabled>{t("character.memory.depInstalling")}</Button>
          ) : (
            <Button onClick={onCloseDependency}>{t("common.close")}</Button>
          )
        }
        onClose={onCloseDependency}
        open={dependencyOpen}
        title={t("character.memory.depMissingTitle")}
      >
        <div className="memory-dep-dialog">
          <p>{t("character.memory.depMissingBody")}</p>
          {dependencyTask ? (
            <TaskProgress logLimit={6} task={dependencyTask} />
          ) : (
            <p className="inline-status">{t("character.memory.depInstalling")}</p>
          )}
        </div>
      </Dialog>

      <Dialog
        closeLabel={t("common.close")}
        footer={<Button onClick={onCloseLoading}>{t("common.cancel")}</Button>}
        onClose={onCloseLoading}
        open={loadingOpen}
        title={t("character.memory.section")}
      >
        <div className="memory-dep-dialog">
          <p>{loadingMessage}</p>
          {loadingTask ? (
            <TaskProgress logLimit={6} task={loadingTask} />
          ) : (
            <span className="memory-dep-progress" role="progressbar" />
          )}
        </div>
      </Dialog>
    </>
  );
}
