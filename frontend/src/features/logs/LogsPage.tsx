import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CaseSensitive, FileText, RefreshCw, Search, Upload } from "lucide-react";

import { getDefaultLog, importLog, logsQueryKey } from "../../entities/logs/repository";
import type { LogSnapshot } from "../../shared/platform/types";
import { AsyncButton, Button, EmptyState, QueryErrorState, Switch, TextInput, useToast } from "../../shared/ui";
import "./LogsPage.css";

type LogLine = {
  level: "debug" | "error" | "info" | "warn" | "default";
  number: number;
  text: string;
};

const MAX_VISIBLE_LINES = 3000;

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

function detectLevel(text: string): LogLine["level"] {
  if (/\b(error|exception|failed|traceback)\b/i.test(text)) {
    return "error";
  }
  if (/\b(warn|warning)\b/i.test(text)) {
    return "warn";
  }
  if (/\bdebug\b/i.test(text)) {
    return "debug";
  }
  if (/\b(info|started|completed|success)\b/i.test(text)) {
    return "info";
  }
  return "default";
}

function buildLines(snapshot?: LogSnapshot): LogLine[] {
  return (snapshot?.content ?? "").split(/\r?\n/).map((text, index) => ({
    level: detectLevel(text),
    number: index + 1,
    text,
  }));
}

function matchesSearch(line: LogLine, query: string, caseSensitive: boolean) {
  const needle = caseSensitive ? query : query.toLowerCase();
  const haystack = caseSensitive ? line.text : line.text.toLowerCase();
  return haystack.includes(needle) || String(line.number).includes(needle);
}

export function LogsPage() {
  const { showToast } = useToast();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [importedLog, setImportedLog] = useState<LogSnapshot | null>(null);
  const [query, setQuery] = useState("");
  const [caseSensitive, setCaseSensitive] = useState(false);
  const logsQuery = useQuery({ queryFn: getDefaultLog, queryKey: logsQueryKey, retry: 1 });
  const activeLog = importedLog ?? logsQuery.data;

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
      setImportedLog(snapshot);
      showToast({ kind: "success", message: snapshot.name, title: "日志已导入" });
    },
  });

  const allLines = useMemo(() => buildLines(activeLog), [activeLog]);
  const filteredLines = useMemo(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      return allLines;
    }
    return allLines.filter((line) => matchesSearch(line, trimmed, caseSensitive));
  }, [allLines, caseSensitive, query]);
  const visibleLines = filteredLines.slice(0, MAX_VISIBLE_LINES);
  const hiddenCount = Math.max(0, filteredLines.length - visibleLines.length);

  const levelCounts = useMemo(
    () =>
      allLines.reduce(
        (counts, line) => {
          counts[line.level] += 1;
          return counts;
        },
        { debug: 0, default: 0, error: 0, info: 0, warn: 0 } satisfies Record<LogLine["level"], number>,
      ),
    [allLines],
  );

  return (
    <div className="page logs-page">
      <header className="page__header">
        <div>
          <h1 className="page__title">日志</h1>
          <p className="page__description">查看运行日志，按关键字搜索，并导入本地日志文件。</p>
        </div>
        <div className="page__actions">
          <Button
            icon={<Upload aria-hidden className="button__icon" />}
            onClick={() => inputRef.current?.click()}
            variant="default"
          >
            导入
          </Button>
          <AsyncButton
            icon={<RefreshCw aria-hidden className="button__icon" />}
            loading={logsQuery.isFetching && !importMutation.isPending}
            onClick={() => {
              setImportedLog(null);
              void logsQuery.refetch();
            }}
            variant="primary"
          >
            刷新
          </AsyncButton>
          <input
            ref={inputRef}
            accept=".log,.txt,.json,.yaml,.yml"
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
            placeholder="搜索文本或行号"
            value={query}
          />
        </div>
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
              <strong>{activeLog?.name ?? "未载入"}</strong>
              <span>{activeLog?.path ?? "-"}</span>
            </div>
          </div>
          <dl className="logs-stats">
            <div>
              <dt>大小</dt>
              <dd>{formatBytes(activeLog?.size ?? 0)}</dd>
            </div>
            <div>
              <dt>修改时间</dt>
              <dd>{formatTimestamp(activeLog?.modifiedAt)}</dd>
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
          {activeLog?.truncated ? <p className="logs-truncated">当前仅显示日志尾部内容。</p> : null}
        </aside>

        <section className="logs-viewer section" aria-label="日志内容">
          {logsQuery.isLoading && !activeLog ? <EmptyState title="正在读取日志" /> : null}
          {logsQuery.isError && !activeLog ? (
            <QueryErrorState
              body="可以导入本地日志文件继续查看。"
              error={logsQuery.error}
              onRetry={() => void logsQuery.refetch()}
              retryLabel="重试"
              title="无法读取默认日志"
            />
          ) : null}
          {!logsQuery.isLoading && activeLog && visibleLines.length === 0 ? (
            <EmptyState body="换一个关键词试试。" title="没有匹配的日志" />
          ) : null}
          {visibleLines.length ? (
            <div className="logs-code" role="log">
              {visibleLines.map((line) => (
                <div className="logs-code__line" data-level={line.level} key={line.number}>
                  <span className="logs-code__number">{line.number}</span>
                  <pre className="logs-code__text">{line.text || " "}</pre>
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
