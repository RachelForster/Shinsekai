import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Archive, CaseSensitive, FileText, RefreshCw, Search, Upload } from "lucide-react";

import {
  exportDiagnosticBundle,
  getDefaultLog,
  importLog,
  listLogFiles,
  logFilesQueryKey,
  logsQueryKey,
  readLog,
} from "../../entities/logs/repository";
import type { LogFileInfo, LogSnapshot, LogStructuredEntry } from "../../shared/platform/types";
import { AsyncButton, Button, EmptyState, QueryErrorState, Select, Switch, TextInput, useToast } from "../../shared/ui";
import { useOptionalChatTheme } from "../chat-stage/theme/ChatThemeProvider";
import "./LogsPage.css";

type LogLevel = "debug" | "error" | "info" | "warn" | "default";

type LogLine = {
  detailPairs: Array<[string, string]>;
  entry?: LogStructuredEntry;
  event: string;
  level: LogLevel;
  logger: string;
  message: string;
  number: number;
  pluginId: string;
  rawText: string;
  taskId: string;
  text: string;
  timestamp: string;
};

const MAX_VISIBLE_LINES = 3000;
const DETAIL_FIELD_LIMIT = 36;
const RESERVED_DETAIL_FIELDS = new Set(["event", "level", "line", "logger", "message", "timestamp"]);

function formatBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size >= 10 || unitIndex === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[unitIndex]}`;
}

function formatTimestamp(value?: number) {
  if (!value) {
    return "-";
  }
  return new Date(value * 1000).toLocaleString();
}

function entryString(entry: LogStructuredEntry | undefined, key: keyof LogStructuredEntry) {
  const value = entry?.[key];
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function valueToDisplay(value: unknown) {
  if (value == null || value === "") {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function entryMessage(entry: LogStructuredEntry | undefined, rawText: string) {
  const message = valueToDisplay(entry?.message).trim();
  if (message) {
    return message;
  }
  const exception = valueToDisplay(entry?.exception).trim();
  if (exception) {
    return exception.split(/\r?\n/, 1)[0] || "Exception";
  }
  const event = entryString(entry, "event");
  if (event) {
    return event;
  }
  return rawText;
}

function entryDetailPairs(entry: LogStructuredEntry | undefined) {
  if (!entry) {
    return [];
  }
  return Object.entries(entry)
    .filter(([key, value]) => !RESERVED_DETAIL_FIELDS.has(key) && value != null && value !== "")
    .slice(0, DETAIL_FIELD_LIMIT)
    .map(([key, value]) => [key, valueToDisplay(value)] as [string, string])
    .filter(([, value]) => value.trim());
}

function normalizeLevel(value: unknown, fallbackText = ""): LogLevel {
  const raw = String(value || "").toLowerCase();
  if (raw.includes("error") || raw.includes("critical") || /\b(exception|failed|traceback)\b/i.test(fallbackText)) {
    return "error";
  }
  if (raw.includes("warn") || /\b(warn|warning)\b/i.test(fallbackText)) {
    return "warn";
  }
  if (raw.includes("debug") || /\bdebug\b/i.test(fallbackText)) {
    return "debug";
  }
  if (raw.includes("info") || /\b(info|started|completed|success)\b/i.test(fallbackText)) {
    return "info";
  }
  return "default";
}

function parseJsonLine(text: string): LogStructuredEntry | undefined {
  const trimmed = text.trim();
  if (!trimmed.startsWith("{")) {
    return undefined;
  }
  try {
    const parsed = JSON.parse(trimmed) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as LogStructuredEntry) : undefined;
  } catch {
    return undefined;
  }
}

function buildLines(snapshot?: LogSnapshot): LogLine[] {
  const entryByLine = new Map<number, LogStructuredEntry>();
  for (const entry of snapshot?.entries ?? []) {
    if (typeof entry.line === "number") {
      entryByLine.set(entry.line, entry);
    }
  }
  return (snapshot?.content ?? "").split(/\r?\n/).map((text, index) => {
    const number = index + 1;
    const entry = entryByLine.get(number) ?? parseJsonLine(text);
    const message = entryMessage(entry, text);
    return {
      detailPairs: entryDetailPairs(entry),
      entry,
      event: entryString(entry, "event"),
      level: normalizeLevel(entry?.level, text),
      logger: entryString(entry, "logger"),
      message,
      number,
      pluginId: entryString(entry, "plugin_id"),
      rawText: text,
      taskId: entryString(entry, "task_id"),
      text: message,
      timestamp: entryString(entry, "timestamp"),
    };
  });
}

function includesQuery(value: string, query: string, caseSensitive: boolean) {
  if (!query) {
    return true;
  }
  const needle = caseSensitive ? query : query.toLowerCase();
  const haystack = caseSensitive ? value : value.toLowerCase();
  return haystack.includes(needle);
}

function lineMatches(
  line: LogLine,
  filters: {
    caseSensitive: boolean;
    event: string;
    level: string;
    logger: string;
    pluginId: string;
    query: string;
  },
) {
  if (filters.level !== "all" && line.level !== filters.level) {
    return false;
  }
  if (filters.logger !== "all" && line.logger !== filters.logger) {
    return false;
  }
  if (filters.event !== "all" && line.event !== filters.event) {
    return false;
  }
  if (filters.pluginId !== "all" && line.pluginId !== filters.pluginId) {
    return false;
  }
  const searchable = [
    line.text,
    line.rawText,
    line.logger,
    line.event,
    line.pluginId,
    line.taskId,
    line.timestamp,
    line.detailPairs.map(([key, value]) => `${key} ${value}`).join(" "),
    String(line.number),
  ].join(" ");
  return includesQuery(searchable, filters.query.trim(), filters.caseSensitive);
}

function optionValues(lines: LogLine[], field: "event" | "logger" | "pluginId") {
  return Array.from(new Set(lines.map((line) => line[field]).filter(Boolean))).sort((a, b) => a.localeCompare(b));
}

function openDownload(url: string) {
  if (!url) {
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

function fileLabel(file: LogFileInfo) {
  return file.relativePath || file.path || file.name;
}

function formatStructuredTimestamp(value: string) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function LogLineBody({ expanded, line, onToggle }: { expanded: boolean; line: LogLine; onToggle: () => void }) {
  const hasStructuredDetails = Boolean(line.entry && line.detailPairs.length);
  const showRaw = line.entry && line.rawText && line.rawText !== line.text;
  const canExpand = hasStructuredDetails || showRaw;
  return (
    <div className="logs-code__body">
      <button
        aria-expanded={canExpand ? expanded : undefined}
        className="logs-code__main"
        disabled={!canExpand}
        onClick={canExpand ? onToggle : undefined}
        type="button"
      >
        <span className="logs-code__summary">
          {line.timestamp ? (
            <span className="logs-code__timestamp">{formatStructuredTimestamp(line.timestamp)}</span>
          ) : null}
          <span className="logs-code__level">{line.level.toUpperCase()}</span>
          {line.logger ? <span className="logs-code__logger">{line.logger}</span> : null}
          {line.event ? <span className="logs-code__event">{line.event}</span> : null}
          {line.pluginId ? <span className="logs-code__chip">plugin {line.pluginId}</span> : null}
          {line.taskId ? <span className="logs-code__chip">task {line.taskId}</span> : null}
          {canExpand ? <span className="logs-code__expand">{expanded ? "收起" : "展开"}</span> : null}
        </span>
        <span className="logs-code__message">{line.text || " "}</span>
      </button>
      {canExpand && expanded ? (
        <div className="logs-code__details">
          {hasStructuredDetails ? (
            <dl className="logs-code__detail-grid">
              {line.detailPairs.map(([key, value]) => (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          ) : null}
          {showRaw ? <pre className="logs-code__raw">{line.rawText}</pre> : null}
        </div>
      ) : null}
    </div>
  );
}

export function LogsPage() {
  const { showToast } = useToast();
  const theme = useOptionalChatTheme();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [activeLog, setActiveLog] = useState<LogSnapshot | null>(null);
  const [activePath, setActivePath] = useState("");
  const [query, setQuery] = useState("");
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [levelFilter, setLevelFilter] = useState("all");
  const [loggerFilter, setLoggerFilter] = useState("all");
  const [eventFilter, setEventFilter] = useState("all");
  const [pluginFilter, setPluginFilter] = useState("all");
  const [expandedLines, setExpandedLines] = useState<Set<number>>(() => new Set());

  const logsQuery = useQuery({ queryFn: getDefaultLog, queryKey: logsQueryKey, retry: 1 });
  const filesQuery = useQuery({ queryFn: listLogFiles, queryKey: logFilesQueryKey, retry: 1 });
  const currentLog = activeLog ?? logsQuery.data;

  const readMutation = useMutation({
    mutationFn: readLog,
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : "日志读取失败。",
        title: "读取失败",
      });
    },
    onSuccess(snapshot) {
      setActiveLog(snapshot);
      setActivePath(snapshot.path);
      setExpandedLines(new Set());
    },
  });

  const importMutation = useMutation({
    mutationFn: (files: File[]) => importLog(files),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : "日志导入失败。",
        title: "导入失败",
      });
    },
    onSuccess(snapshot) {
      setActiveLog(snapshot);
      setActivePath(snapshot.path);
      setExpandedLines(new Set());
      showToast({ kind: "success", message: snapshot.name, title: "日志已导入" });
    },
  });

  const diagnosticsMutation = useMutation({
    mutationFn: exportDiagnosticBundle,
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : "诊断包生成失败。",
        title: "导出失败",
      });
    },
    onSuccess(result) {
      showToast({ kind: "success", message: result.path, title: "诊断包已生成" });
      openDownload(result.downloadUrl);
    },
  });

  const allLines = useMemo(() => buildLines(currentLog), [currentLog]);
  const loggerOptions = useMemo(() => optionValues(allLines, "logger"), [allLines]);
  const eventOptions = useMemo(() => optionValues(allLines, "event"), [allLines]);
  const pluginOptions = useMemo(() => optionValues(allLines, "pluginId"), [allLines]);
  const filteredLines = useMemo(
    () =>
      allLines.filter((line) =>
        lineMatches(line, {
          caseSensitive,
          event: eventFilter,
          level: levelFilter,
          logger: loggerFilter,
          pluginId: pluginFilter,
          query,
        }),
      ),
    [allLines, caseSensitive, eventFilter, levelFilter, loggerFilter, pluginFilter, query],
  );
  const visibleLines = filteredLines.slice(0, MAX_VISIBLE_LINES);
  const hiddenCount = Math.max(0, filteredLines.length - visibleLines.length);

  const levelCounts = useMemo(
    () =>
      allLines.reduce(
        (counts, line) => {
          counts[line.level] += 1;
          return counts;
        },
        { debug: 0, default: 0, error: 0, info: 0, warn: 0 } satisfies Record<LogLevel, number>,
      ),
    [allLines],
  );

  const resetToDefaultLog = () => {
    setActiveLog(null);
    setActivePath("");
    setExpandedLines(new Set());
    void logsQuery.refetch();
    void filesQuery.refetch();
  };

  const toggleExpandedLine = (lineNumber: number) => {
    setExpandedLines((current) => {
      const next = new Set(current);
      if (next.has(lineNumber)) {
        next.delete(lineNumber);
      } else {
        next.add(lineNumber);
      }
      return next;
    });
  };

  return (
    <div className="page logs-page" style={theme?.style}>
      <header className="page__header">
        <div>
          <h1 className="page__title">日志</h1>
          <p className="page__description">查看运行日志，按结构化字段筛选，并导出诊断包。</p>
        </div>
        <div className="page__actions">
          <Button icon={<Upload aria-hidden className="button__icon" />} onClick={() => inputRef.current?.click()}>
            导入
          </Button>
          <AsyncButton
            icon={<Archive aria-hidden className="button__icon" />}
            loading={diagnosticsMutation.isPending}
            onClick={() => diagnosticsMutation.mutate()}
            variant="ghost"
          >
            诊断包
          </AsyncButton>
          <AsyncButton
            icon={<RefreshCw aria-hidden className="button__icon" />}
            loading={(logsQuery.isFetching || filesQuery.isFetching) && !importMutation.isPending}
            onClick={resetToDefaultLog}
            variant="primary"
          >
            刷新
          </AsyncButton>
          <input
            ref={inputRef}
            accept=".log,.txt,.json,.jsonl,.yaml,.yml"
            className="logs-page__file-input"
            onChange={(event) => {
              const files = Array.from(event.target.files ?? []);
              if (files.length) {
                importMutation.mutate(files);
              }
              event.target.value = "";
            }}
            type="file"
          />
        </div>
      </header>

      <section className="logs-toolbar section" aria-label="日志搜索">
        <div className="logs-toolbar__search">
          <Search aria-hidden className="logs-toolbar__icon" />
          <TextInput
            aria-label="搜索日志"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索文本、行号、事件、任务 ID"
            value={query}
          />
        </div>
        <Select aria-label="日志级别" onChange={(event) => setLevelFilter(event.target.value)} value={levelFilter}>
          <option value="all">全部级别</option>
          <option value="error">Error</option>
          <option value="warn">Warn</option>
          <option value="info">Info</option>
          <option value="debug">Debug</option>
          <option value="default">Other</option>
        </Select>
        <Select aria-label="Logger" onChange={(event) => setLoggerFilter(event.target.value)} value={loggerFilter}>
          <option value="all">全部 logger</option>
          {loggerOptions.map((logger) => (
            <option key={logger} value={logger}>
              {logger}
            </option>
          ))}
        </Select>
        <Select aria-label="Event" onChange={(event) => setEventFilter(event.target.value)} value={eventFilter}>
          <option value="all">全部事件</option>
          {eventOptions.map((event) => (
            <option key={event} value={event}>
              {event}
            </option>
          ))}
        </Select>
        <Select aria-label="Plugin" onChange={(event) => setPluginFilter(event.target.value)} value={pluginFilter}>
          <option value="all">全部插件</option>
          {pluginOptions.map((plugin) => (
            <option key={plugin} value={plugin}>
              {plugin}
            </option>
          ))}
        </Select>
        <Switch
          checked={caseSensitive}
          id="logs-case-sensitive"
          onChange={(event) => setCaseSensitive(event.target.checked)}
        >
          <CaseSensitive aria-hidden className="logs-toolbar__switch-icon" />
          区分大小写
        </Switch>
      </section>

      <div className="logs-layout">
        <aside className="logs-sidebar section">
          <div className="logs-source">
            <FileText aria-hidden className="logs-source__icon" />
            <div className="logs-source__text">
              <strong>{currentLog?.name ?? "未载入"}</strong>
              <span>{currentLog?.path ?? "-"}</span>
            </div>
          </div>
          <dl className="logs-stats">
            <div>
              <dt>大小</dt>
              <dd>{formatBytes(currentLog?.size ?? 0)}</dd>
            </div>
            <div>
              <dt>修改时间</dt>
              <dd>{formatTimestamp(currentLog?.modifiedAt)}</dd>
            </div>
            <div>
              <dt>行数</dt>
              <dd>{allLines.length}</dd>
            </div>
            <div>
              <dt>匹配</dt>
              <dd>{filteredLines.length}</dd>
            </div>
          </dl>
          <div className="logs-levels" aria-label="日志级别统计">
            <span data-level="error">Error {levelCounts.error}</span>
            <span data-level="warn">Warn {levelCounts.warn}</span>
            <span data-level="info">Info {levelCounts.info}</span>
            <span data-level="debug">Debug {levelCounts.debug}</span>
          </div>
          {currentLog?.truncated ? <p className="logs-truncated">当前仅显示日志尾部内容。</p> : null}

          <div className="logs-file-list">
            <h2 className="section__title">最近日志</h2>
            {filesQuery.isError ? <p className="logs-truncated">日志列表读取失败。</p> : null}
            {(filesQuery.data?.files ?? []).map((file) => (
              <button
                className="logs-file-list__item"
                data-active={activePath ? file.path === activePath : file.path === logsQuery.data?.path}
                disabled={readMutation.isPending}
                key={file.path}
                onClick={() => readMutation.mutate(file.path)}
                type="button"
              >
                <span>{fileLabel(file)}</span>
                <small>
                  {formatBytes(file.size)} · {formatTimestamp(file.modifiedAt)}
                </small>
              </button>
            ))}
          </div>
        </aside>

        <section className="logs-viewer section" aria-label="日志内容">
          {logsQuery.isLoading && !currentLog ? <EmptyState title="正在读取日志" /> : null}
          {logsQuery.isError && !currentLog ? (
            <QueryErrorState
              body="可以导入本地日志文件继续查看。"
              error={logsQuery.error}
              onRetry={() => void logsQuery.refetch()}
              retryLabel="重试"
              title="无法读取默认日志"
            />
          ) : null}
          {!logsQuery.isLoading && currentLog && visibleLines.length === 0 ? (
            <EmptyState body="换一个筛选条件试试。" title="没有匹配的日志" />
          ) : null}
          {visibleLines.length ? (
            <div className="logs-code" role="log">
              {visibleLines.map((line) => (
                <div
                  className="logs-code__line"
                  data-expanded={expandedLines.has(line.number)}
                  data-level={line.level}
                  key={line.number}
                >
                  <span className="logs-code__number">{line.number}</span>
                  <LogLineBody
                    expanded={expandedLines.has(line.number)}
                    line={line}
                    onToggle={() => toggleExpandedLine(line.number)}
                  />
                </div>
              ))}
            </div>
          ) : null}
          {hiddenCount ? <p className="logs-hidden-count">还有 {hiddenCount} 行未显示。</p> : null}
        </section>
      </div>
    </div>
  );
}
