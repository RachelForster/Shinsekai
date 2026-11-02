import { useEffect, useId, useMemo, useState, type CSSProperties, type FormEvent } from "react";
import { Check, ChevronDown, ChevronRight, GitBranch, Pencil, X } from "lucide-react";

import { useI18n } from "../../../shared/i18n";
import type { ChatConversationBranch, ChatConversationTree } from "../../../shared/platform/types";
import { Button } from "../../../shared/ui";
import { ChatStageModal } from "./ChatStageModal";

function fallbackBranches(tree?: ChatConversationTree): ChatConversationBranch[] {
  if (tree?.branches?.length) {
    return tree.branches;
  }
  return [{ id: "main", label: "Main", parentId: null }];
}

interface VisibleBranchNode {
  branch: ChatConversationBranch;
  childCount: number;
  collapsed: boolean;
  depth: number;
}

function collectVisibleBranches(branches: ChatConversationBranch[], collapsedIds: Set<string>): VisibleBranchNode[] {
  const byId = new Map(branches.map((item) => [item.id, item]));
  const childrenByParent = new Map<string | null, ChatConversationBranch[]>();
  for (const branch of branches) {
    const parentId = branch.parentId && byId.has(branch.parentId) ? branch.parentId : null;
    const children = childrenByParent.get(parentId) ?? [];
    children.push(branch);
    childrenByParent.set(parentId, children);
  }

  const visible: VisibleBranchNode[] = [];
  const visited = new Set<string>();
  const append = (parentId: string | null, depth: number, path: Set<string>) => {
    for (const branch of childrenByParent.get(parentId) ?? []) {
      if (visited.has(branch.id) || path.has(branch.id)) {
        continue;
      }
      const childCount = childrenByParent.get(branch.id)?.length ?? 0;
      const collapsed = collapsedIds.has(branch.id);
      visible.push({ branch, childCount, collapsed, depth });
      visited.add(branch.id);
      if (childCount > 0 && !collapsed) {
        append(branch.id, depth + 1, new Set([...path, branch.id]));
      }
    }
  };

  append(null, 0, new Set());
  return visible;
}

export function ConversationTreeDialog({
  onClose,
  onRenameBranch,
  onSwitchBranch,
  open,
  tree,
}: {
  onClose: () => void;
  onRenameBranch: (branchId: string, label: string) => void;
  onSwitchBranch: (branchId: string) => void;
  open: boolean;
  tree?: ChatConversationTree;
}) {
  const { t } = useI18n();
  const titleId = useId();
  const [collapsedIds, setCollapsedIds] = useState<Set<string>>(new Set());
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const branches = useMemo(() => fallbackBranches(tree), [tree]);
  const branchIds = useMemo(() => new Set(branches.map((branch) => branch.id)), [branches]);
  const visibleBranches = useMemo(() => collectVisibleBranches(branches, collapsedIds), [branches, collapsedIds]);
  const activeBranchId = tree?.activeBranchId || branches[0]?.id || "main";
  const largeTree = branches.length > 200;

  useEffect(() => {
    setCollapsedIds((current) => {
      const next = new Set([...current].filter((branchId) => branchIds.has(branchId)));
      return next.size === current.size ? current : next;
    });
  }, [branchIds]);

  if (!open) {
    return null;
  }

  const toggleCollapsed = (branchId: string) => {
    setCollapsedIds((current) => {
      const next = new Set(current);
      if (next.has(branchId)) {
        next.delete(branchId);
      } else {
        next.add(branchId);
      }
      return next;
    });
  };
  const beginRename = (branch: ChatConversationBranch) => {
    setRenamingId(branch.id);
    setRenameValue(branch.label || branch.id);
  };
  const cancelRename = () => {
    setRenamingId(null);
    setRenameValue("");
  };
  const submitRename = (event: FormEvent<HTMLFormElement>, branch: ChatConversationBranch) => {
    event.preventDefault();
    const label = renameValue.trim();
    if (label && label !== (branch.label || branch.id)) {
      onRenameBranch(branch.id, label);
    }
    cancelRename();
  };

  return (
    <ChatStageModal
      backdropClassName="chat-branch-backdrop"
      closeLabel={t("common.close")}
      dialogClassName="chat-branch-dialog"
      eyebrow={t("chat.branches.eyebrow")}
      labelledBy={titleId}
      onClose={onClose}
      open={open}
      summary={t("chat.branches.count", { count: branches.length, visible: visibleBranches.length })}
      title={t("chat.branches.title")}
    >
      <div className="chat-stage-modal__body chat-branch-dialog__body">
        {largeTree ? <p className="chat-branch-dialog__notice">{t("chat.branches.largeTree")}</p> : null}
        <div className="chat-branch-tree" role="list">
          {visibleBranches.map(({ branch, childCount, collapsed, depth }) => {
            const active = branch.id === activeBranchId;
            const label = branch.label || branch.id;
            const editing = renamingId === branch.id;
            return (
              <article
                className="chat-branch-tree__node"
                data-active={active ? "true" : "false"}
                key={branch.id}
                role="listitem"
                style={{ "--branch-depth": String(depth) } as CSSProperties}
              >
                <div className="chat-branch-tree__rail">
                  {childCount > 0 ? (
                    <button
                      aria-expanded={!collapsed}
                      aria-label={t(collapsed ? "chat.branches.expand" : "chat.branches.collapse", { name: label })}
                      className="chat-branch-tree__toggle"
                      onClick={() => toggleCollapsed(branch.id)}
                      type="button"
                    >
                      {collapsed ? (
                        <ChevronRight aria-hidden className="chat-branch-tree__toggle-icon" />
                      ) : (
                        <ChevronDown aria-hidden className="chat-branch-tree__toggle-icon" />
                      )}
                    </button>
                  ) : (
                    <span className="chat-branch-tree__leaf" aria-hidden />
                  )}
                </div>
                <div className="chat-branch-tree__content">
                  {editing ? (
                    <form className="chat-branch-tree__rename" onSubmit={(event) => submitRename(event, branch)}>
                      <input
                        aria-label={t("chat.branches.renameInput")}
                        autoFocus
                        className="chat-branch-tree__name-input"
                        onChange={(event) => setRenameValue(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Escape") {
                            event.stopPropagation();
                            cancelRename();
                          }
                        }}
                        value={renameValue}
                      />
                      <div className="chat-branch-tree__rename-actions">
                        <button
                          aria-label={t("chat.branches.saveName")}
                          className="chat-branch-tree__rename-button"
                          type="submit"
                        >
                          <Check aria-hidden className="chat-branch-tree__rename-icon" />
                        </button>
                        <button
                          aria-label={t("chat.branches.cancelRename")}
                          className="chat-branch-tree__rename-button"
                          onClick={cancelRename}
                          type="button"
                        >
                          <X aria-hidden className="chat-branch-tree__rename-icon" />
                        </button>
                      </div>
                    </form>
                  ) : (
                    <div className="chat-branch-tree__meta">
                      <GitBranch aria-hidden className="chat-branch-tree__icon" />
                      <span className="chat-branch-tree__label">{label}</span>
                      {active ? <span className="chat-branch-tree__active">{t("chat.branches.active")}</span> : null}
                    </div>
                  )}
                  {branch.forkedFromText ? (
                    <p className="chat-branch-tree__forked">
                      {t("chat.branches.forkedFrom", { text: branch.forkedFromText })}
                    </p>
                  ) : (
                    <p className="chat-branch-tree__forked">{t("chat.branches.root")}</p>
                  )}
                </div>
                <div className="chat-branch-tree__actions">
                  <button
                    aria-label={t("chat.branches.rename", { name: label })}
                    className="chat-branch-tree__edit"
                    onClick={() => beginRename(branch)}
                    type="button"
                  >
                    <Pencil aria-hidden className="chat-branch-tree__edit-icon" />
                  </button>
                  <Button disabled={active} onClick={() => onSwitchBranch(branch.id)}>
                    {active ? t("chat.branches.current") : t("chat.branches.switch")}
                  </Button>
                </div>
              </article>
            );
          })}
        </div>
      </div>
    </ChatStageModal>
  );
}
