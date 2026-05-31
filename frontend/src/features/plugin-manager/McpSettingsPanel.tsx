import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileJson, FolderOpen, Plus, RefreshCw, Save, Trash2 } from "lucide-react";

import {
  getMcpConfig,
  mcpConfigQueryKey,
  openMcpConfigFile,
  previewMcpTools,
  saveAndApplyMcpConfig,
} from "../../entities/plugin/repository";
import type { McpConfig, McpServerEntry, McpToolPreview, McpTransport } from "../../entities/plugin/types";
import { useI18n } from "../../shared/i18n";
import type { TaskSnapshot } from "../../shared/platform/types";
import {
  AlertDialog,
  AsyncButton,
  Button,
  DataTable,
  Switch,
  Dialog,
  EmptyState,
  NumberInput,
  QueryErrorState,
  Select,
  TaskProgress,
  TextArea,
  TextInput,
  useToast,
} from "../../shared/ui";

type ServerDialogState = { index: number | null; server: McpServerEntry } | null;
type McpServerRow = McpServerEntry & { index: number; rowKey: string };

function emptyServer(): McpServerEntry {
  return {
    enabled: true,
    name_prefix: "",
    transport: "sse",
    url: "",
  };
}

function formatJson(value: unknown, fallback: unknown) {
  return JSON.stringify(value ?? fallback, null, 2);
}

function parseObjectJson(text: string, message: string): Record<string, string> {
  if (!text.trim()) {
    return {};
  }
  const parsed = JSON.parse(text);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(message);
  }
  return Object.fromEntries(Object.entries(parsed).map(([key, value]) => [key, String(value)]));
}

function parseArrayJson(text: string, message: string): string[] {
  if (!text.trim()) {
    return [];
  }
  const parsed = JSON.parse(text);
  if (!Array.isArray(parsed)) {
    throw new Error(message);
  }
  return parsed.map(String);
}

function normalizeTransport(value: unknown): McpTransport {
  const raw = String(value || "sse")
    .trim()
    .toLowerCase();
  if (raw === "stdio") {
    return "stdio";
  }
  if (raw === "streamable_http" || raw === "streamablehttp" || raw === "streamable-http" || raw === "http") {
    return "streamable_http";
  }
  return "sse";
}

function connectionSummary(server: McpServerEntry) {
  if (server.transport === "stdio") {
    const args = server.args ?? [];
    const head = args.slice(0, 6);
    const suffix = args.length > 6 ? "..." : "";
    return [server.command, ...head, suffix].filter(Boolean).join(" ");
  }
  return server.url ?? "";
}

function importMcpServers(rawText: string): McpServerEntry[] {
  const raw = JSON.parse(rawText);
  const servers = raw?.mcpServers;
  if (!servers || typeof servers !== "object" || Array.isArray(servers)) {
    return [];
  }
  return Object.entries(servers).flatMap(([name, value]) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return [];
    }
    const source = value as Record<string, unknown>;
    const transport = normalizeTransport(source.type ?? source.transport);
    const entry: McpServerEntry = {
      enabled: true,
      name_prefix: `${name}_`,
      transport,
    };
    if (typeof source.group === "string" && source.group.trim()) {
      entry.group = source.group.trim();
    }
    const timeout = Number(source.call_timeout ?? source.timeout);
    if (Number.isFinite(timeout) && timeout > 0) {
      entry.call_timeout = timeout;
    }
    if (transport === "stdio") {
      entry.command = String(source.command ?? "");
      entry.args = Array.isArray(source.args) ? source.args.map(String) : [];
      entry.env =
        source.env && typeof source.env === "object" && !Array.isArray(source.env)
          ? Object.fromEntries(Object.entries(source.env).map(([key, item]) => [key, String(item)]))
          : {};
      return [entry];
    }
    entry.url = String(source.url ?? "");
    entry.headers =
      source.headers && typeof source.headers === "object" && !Array.isArray(source.headers)
        ? Object.fromEntries(Object.entries(source.headers).map(([key, item]) => [key, String(item)]))
        : {};
    return [entry];
  });
}

function McpServerDialog({
  initial,
  onClose,
  onSave,
  open,
  title,
}: {
  initial: McpServerEntry;
  onClose: () => void;
  onSave: (server: McpServerEntry) => void;
  open: boolean;
  title: string;
}) {
  const { t } = useI18n();
  const [server, setServer] = useState(initial);
  const [headersText, setHeadersText] = useState("{}");
  const [argsText, setArgsText] = useState("[]");
  const [envText, setEnvText] = useState("{}");
  const [callTimeoutText, setCallTimeoutText] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) {
      return;
    }
    setServer(initial);
    setHeadersText(formatJson(initial.headers, {}));
    setArgsText(formatJson(initial.args, []));
    setEnvText(formatJson(initial.env, {}));
    setCallTimeoutText(initial.call_timeout == null ? "" : String(initial.call_timeout));
    setError("");
  }, [initial, open]);

  const update = (patch: Partial<McpServerEntry>) => setServer((current) => ({ ...current, ...patch }));

  const handleSave = () => {
    try {
      const next: McpServerEntry = {
        enabled: server.enabled,
        name_prefix: server.name_prefix.trim(),
        transport: server.transport,
      };
      const timeout = callTimeoutText.trim() ? Number(callTimeoutText) : null;
      if (timeout != null) {
        if (!Number.isFinite(timeout) || timeout < 0) {
          throw new Error(t("mcp.validation.defaultTimeout"));
        }
        if (timeout > 0) {
          next.call_timeout = timeout;
        }
      }
      if (server.group?.trim()) {
        next.group = server.group.trim();
      }
      if (server.transport === "stdio") {
        if (!server.command?.trim()) {
          throw new Error(t("mcp.validation.needCommand"));
        }
        next.command = server.command.trim();
        next.args = parseArrayJson(argsText, t("mcp.validation.argsArray"));
        next.env = parseObjectJson(envText, t("mcp.validation.envObject"));
      } else {
        if (!server.url?.trim()) {
          throw new Error(t("mcp.validation.needUrl"));
        }
        next.url = server.url.trim();
        next.headers = parseObjectJson(headersText, t("mcp.validation.headersObject"));
      }
      onSave(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <Dialog
      closeLabel={t("common.close")}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button icon={<Save aria-hidden className="button__icon" />} onClick={handleSave} variant="primary">
            {t("mcp.action.saveServer")}
          </Button>
        </>
      }
      onClose={onClose}
      open={open}
      title={title}
    >
      <div className="form-grid">
        <label className="field-row">
          <span className="field-row__label">{t("mcp.enabled")}</span>
          <span className="field-row__control">
            <Switch checked={server.enabled} onChange={(event) => update({ enabled: event.target.checked })} />
          </span>
        </label>
        <label className="field-row">
          <span className="field-row__label">{t("mcp.field.prefix")}</span>
          <span className="field-row__control">
            <TextInput onChange={(event) => update({ name_prefix: event.target.value })} value={server.name_prefix} />
          </span>
        </label>
        <label className="field-row">
          <span className="field-row__label">{t("mcp.field.callTimeout")}</span>
          <span className="field-row__control">
            <NumberInput min={0} onChange={(event) => setCallTimeoutText(event.target.value)} value={callTimeoutText} />
          </span>
        </label>
        <label className="field-row">
          <span className="field-row__label">{t("mcp.field.transport")}</span>
          <span className="field-row__control">
            <Select
              onChange={(event) => update({ transport: event.target.value as McpTransport })}
              value={server.transport}
            >
              <option value="sse">SSE</option>
              <option value="streamable_http">Streamable HTTP</option>
              <option value="stdio">stdio</option>
            </Select>
          </span>
        </label>
        <label className="field-row">
          <span className="field-row__label">{t("mcp.field.group")}</span>
          <span className="field-row__control">
            <TextInput
              onChange={(event) => update({ group: event.target.value })}
              placeholder="mcp"
              value={server.group ?? ""}
            />
          </span>
        </label>

        {server.transport === "stdio" ? (
          <>
            <label className="field-row">
              <span className="field-row__label">{t("mcp.field.command")}</span>
              <span className="field-row__control">
                <TextInput onChange={(event) => update({ command: event.target.value })} value={server.command ?? ""} />
              </span>
            </label>
            <label className="field-row">
              <span className="field-row__label">{t("mcp.field.args")}</span>
              <span className="field-row__control">
                <TextArea onChange={(event) => setArgsText(event.target.value)} value={argsText} />
              </span>
            </label>
            <label className="field-row">
              <span className="field-row__label">{t("mcp.field.env")}</span>
              <span className="field-row__control">
                <TextArea onChange={(event) => setEnvText(event.target.value)} value={envText} />
              </span>
            </label>
          </>
        ) : (
          <>
            <label className="field-row">
              <span className="field-row__label">{t("mcp.field.url")}</span>
              <span className="field-row__control">
                <TextInput onChange={(event) => update({ url: event.target.value })} value={server.url ?? ""} />
              </span>
            </label>
            <label className="field-row">
              <span className="field-row__label">{t("mcp.field.headers")}</span>
              <span className="field-row__control">
                <TextArea onChange={(event) => setHeadersText(event.target.value)} value={headersText} />
              </span>
            </label>
          </>
        )}

        {error ? (
          <div className="field-error" role="alert">
            {error}
          </div>
        ) : null}
      </div>
    </Dialog>
  );
}

export function McpSettingsPanel() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { t } = useI18n();
  const mcpConfigQuery = useQuery({ queryFn: getMcpConfig, queryKey: mcpConfigQueryKey });
  const { data, isLoading } = mcpConfigQuery;
  const [draft, setDraft] = useState<McpConfig | null>(null);
  const [serverDialog, setServerDialog] = useState<ServerDialogState>(null);
  const [deleteIndex, setDeleteIndex] = useState<number | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState("");
  const [importError, setImportError] = useState("");
  const [applyTask, setApplyTask] = useState<TaskSnapshot<McpConfig> | null>(null);
  const [previewTask, setPreviewTask] = useState<TaskSnapshot<McpToolPreview[]> | null>(null);
  const [tools, setTools] = useState<McpToolPreview[]>([]);

  useEffect(() => {
    if (data) {
      setDraft(data);
    }
  }, [data]);

  const rows = useMemo<McpServerRow[]>(
    () =>
      (draft?.servers ?? []).map((server, index) => ({
        ...server,
        index,
        rowKey: `${index}-${server.transport}-${server.name_prefix}-${connectionSummary(server)}`,
      })),
    [draft],
  );
  const controlsEnabled = draft?.enabled !== false;

  const saveMutation = useMutation({
    mutationFn: (config: McpConfig) => saveAndApplyMcpConfig(config, { onTaskUpdate: setApplyTask }),
    onMutate() {
      setApplyTask(null);
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("mcp.installHint"),
        title: t("mcp.toast.operationFailed"),
      });
    },
    onSuccess(nextConfig) {
      setDraft(nextConfig);
      queryClient.invalidateQueries({ queryKey: mcpConfigQueryKey });
      showToast({ kind: "success", title: t("mcp.toast.saveSuccess") });
    },
  });

  const previewMutation = useMutation({
    mutationFn: (config: McpConfig) => previewMcpTools(config, { onTaskUpdate: setPreviewTask }),
    onMutate() {
      setPreviewTask(null);
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("mcp.installHint"),
        title: t("mcp.toast.operationFailed"),
      });
    },
    onSuccess(nextTools) {
      setTools(nextTools);
      showToast({ kind: "success", message: `${nextTools.length}`, title: t("mcp.toast.previewSuccess") });
    },
  });

  const openMutation = useMutation({
    mutationFn: openMcpConfigFile,
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : "",
        title: t("mcp.toast.operationFailed"),
      });
    },
    onSuccess(path) {
      showToast({ kind: "success", message: path, title: t("mcp.toast.opened") });
    },
  });

  const updateDraft = (patch: Partial<McpConfig>) => {
    setDraft((current) => (current ? { ...current, ...patch } : current));
  };

  const saveServer = (server: McpServerEntry) => {
    setDraft((current) => {
      if (!current) {
        return current;
      }
      const servers = [...current.servers];
      if (serverDialog?.index == null) {
        servers.push(server);
      } else {
        servers[serverDialog.index] = server;
      }
      return { ...current, servers };
    });
    setServerDialog(null);
  };

  const deleteServer = () => {
    if (deleteIndex == null) {
      return;
    }
    setDraft((current) =>
      current ? { ...current, servers: current.servers.filter((_, index) => index !== deleteIndex) } : current,
    );
    setDeleteIndex(null);
  };

  const applyImport = () => {
    try {
      const imported = importMcpServers(importText);
      if (!imported.length) {
        throw new Error(t("mcp.importJson.noServers"));
      }
      setDraft((current) => (current ? { ...current, servers: [...current.servers, ...imported] } : current));
      setImportOpen(false);
      setImportText("");
      setImportError("");
      showToast({
        kind: "success",
        message: t("mcp.importJson.okBody", { count: imported.length }),
        title: t("mcp.toast.importSuccess"),
      });
    } catch (error) {
      setImportError(error instanceof Error ? error.message : String(error));
      showToast({ kind: "error", title: t("mcp.toast.importFailed") });
    }
  };

  const serverColumns = [
    {
      header: t("mcp.enabled"),
      key: "enabled",
      render: (server: McpServerRow) => (server.enabled ? t("mcp.status.yes") : t("mcp.status.no")),
    },
    {
      header: t("mcp.field.prefix"),
      key: "prefix",
      render: (server: McpServerRow) => server.name_prefix || "-",
    },
    {
      header: t("mcp.field.transport"),
      key: "transport",
      render: (server: McpServerRow) => server.transport.toUpperCase(),
    },
    {
      header: t("mcp.field.connection"),
      key: "connection",
      render: (server: McpServerRow) => <span className="inline-status">{connectionSummary(server) || "-"}</span>,
    },
    {
      header: "",
      key: "actions",
      render: (server: McpServerRow) => (
        <div className="page__actions">
          <Button
            disabled={!controlsEnabled}
            onClick={() => setServerDialog({ index: server.index, server })}
            variant="ghost"
          >
            {t("common.edit")}
          </Button>
          <Button
            disabled={!controlsEnabled}
            icon={<Trash2 aria-hidden className="button__icon" />}
            onClick={() => setDeleteIndex(server.index)}
            variant="ghost"
          >
            {t("common.delete")}
          </Button>
        </div>
      ),
    },
  ];

  const toolColumns = [
    {
      header: t("mcp.field.prefix"),
      key: "prefix",
      render: (tool: McpToolPreview) => tool.prefix || "-",
    },
    {
      header: t("mcp.field.registeredName"),
      key: "registered_name",
      render: (tool: McpToolPreview) => tool.registered_name,
    },
    {
      header: t("mcp.field.toolName"),
      key: "name",
      render: (tool: McpToolPreview) => tool.name,
    },
    {
      header: t("common.description"),
      key: "description",
      render: (tool: McpToolPreview) => <span className="inline-status">{tool.description}</span>,
    },
  ];

  if (mcpConfigQuery.isError) {
    return (
      <QueryErrorState
        body={t("mcp.installHint")}
        error={mcpConfigQuery.error}
        onRetry={() => void mcpConfigQuery.refetch()}
        retryLabel={t("common.retry")}
        title={t("common.operationFailed")}
      />
    );
  }

  if (isLoading || !draft) {
    return <EmptyState title={t("mcp.preview.loading")} />;
  }

  return (
    <>
      <section className="section">
        <div className="section__header">
          <div>
            <h2 className="section__title">MCP</h2>
            <p className="section__description">{t("mcp.description")}</p>
          </div>
          <div className="page__actions">
            <Button
              icon={<FolderOpen aria-hidden className="button__icon" />}
              loading={openMutation.isPending}
              onClick={() => openMutation.mutate()}
              variant="ghost"
            >
              {t("mcp.action.openYaml")}
            </Button>
            <AsyncButton
              icon={<Save aria-hidden className="button__icon" />}
              loading={saveMutation.isPending}
              onClick={() => saveMutation.mutate(draft)}
              variant="primary"
            >
              {t("common.saveApply")}
            </AsyncButton>
          </div>
        </div>

        <div className="form-grid form-grid--two">
          <label className="field-row">
            <span className="field-row__label">{t("mcp.globalEnable")}</span>
            <span className="field-row__control">
              <Switch checked={draft.enabled} onChange={(event) => updateDraft({ enabled: event.target.checked })} />
            </span>
          </label>
          <label className="field-row">
            <span className="field-row__label">{t("mcp.defaultTimeout")}</span>
            <span className="field-row__control">
              <NumberInput
                min={1}
                onChange={(event) => updateDraft({ default_call_timeout: Number(event.target.value) })}
                value={draft.default_call_timeout}
              />
            </span>
          </label>
        </div>
        <TaskProgress task={applyTask} />
      </section>

      <section className="section">
        <div className="section__header">
          <h2 className="section__title">{t("mcp.server.title")}</h2>
          <div className="page__actions">
            <Button
              icon={<FileJson aria-hidden className="button__icon" />}
              onClick={() => setImportOpen(true)}
              variant="ghost"
            >
              {t("mcp.importJson")}
            </Button>
            <Button
              disabled={!controlsEnabled}
              icon={<Plus aria-hidden className="button__icon" />}
              onClick={() => setServerDialog({ index: null, server: emptyServer() })}
            >
              {t("common.add")}
            </Button>
          </div>
        </div>
        {rows.length ? (
          <DataTable columns={serverColumns} getRowKey={(server) => server.rowKey} rows={rows} />
        ) : (
          <EmptyState title={t("mcp.server.emptyTitle")} body={t("mcp.server.emptyBody")} />
        )}
      </section>

      <section className="section">
        <div className="section__header">
          <h2 className="section__title">{t("mcp.tools.title")}</h2>
          <AsyncButton
            disabled={!controlsEnabled}
            icon={<RefreshCw aria-hidden className="button__icon" />}
            loading={previewMutation.isPending}
            onClick={() => previewMutation.mutate(draft)}
            variant="ghost"
          >
            {t("mcp.action.previewTools")}
          </AsyncButton>
        </div>
        <TaskProgress task={previewTask} />
        {tools.length ? (
          <DataTable columns={toolColumns} getRowKey={(tool) => tool.registered_name || tool.name} rows={tools} />
        ) : (
          <EmptyState title={t("mcp.preview.empty")} body={t("mcp.preview.emptyBody")} />
        )}
      </section>

      <McpServerDialog
        initial={serverDialog?.server ?? emptyServer()}
        onClose={() => setServerDialog(null)}
        onSave={saveServer}
        open={Boolean(serverDialog)}
        title={serverDialog?.index == null ? t("mcp.dialog.addTitle") : t("mcp.dialog.editTitle")}
      />

      <Dialog
        closeLabel={t("common.close")}
        footer={
          <>
            <Button onClick={() => setImportOpen(false)}>{t("common.cancel")}</Button>
            <Button icon={<FileJson aria-hidden className="button__icon" />} onClick={applyImport} variant="primary">
              {t("mcp.importJson")}
            </Button>
          </>
        }
        onClose={() => setImportOpen(false)}
        open={importOpen}
        title={t("mcp.importJson.title")}
      >
        <div className="form-grid">
          <p className="section__description">{t("mcp.importJson.hint")}</p>
          <TextArea onChange={(event) => setImportText(event.target.value)} rows={10} value={importText} />
          {importError ? (
            <div className="field-error" role="alert">
              {importError}
            </div>
          ) : null}
        </div>
      </Dialog>

      <AlertDialog
        body={t("mcp.delete.confirmBody")}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={t("common.delete")}
        onCancel={() => setDeleteIndex(null)}
        onConfirm={deleteServer}
        open={deleteIndex != null}
        title={t("mcp.delete.confirmTitle")}
      />
    </>
  );
}
