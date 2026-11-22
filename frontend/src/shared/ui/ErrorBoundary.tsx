import { Component, type ErrorInfo, type ReactNode } from "react";
import { RefreshCw, RotateCcw } from "lucide-react";

import { I18nContext, translateMessage } from "../i18n";
import "./ErrorBoundary.css";
import { Button } from "./Button";

interface ErrorBoundaryProps {
  children: ReactNode;
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    this.props.onError?.(error, errorInfo);
  }

  private reset = () => {
    this.setState({ error: null });
  };

  private reload = () => {
    window.location.reload();
  };

  render() {
    const { error } = this.state;
    if (error) {
      return (
        <I18nContext.Consumer>
          {(i18n) => {
            const t = i18n?.t ?? ((key, values) => translateMessage("zh_CN", key, values));
            return (
              <main className="error-boundary" role="alert">
                <section className="error-boundary__panel">
                  <div>
                    <p className="error-boundary__eyebrow">React runtime</p>
                    <h1 className="error-boundary__title">{t("errorBoundary.title")}</h1>
                    <p className="error-boundary__body">{t("errorBoundary.body")}</p>
                  </div>
                  <pre className="error-boundary__detail">{error.message}</pre>
                  <div className="inline-actions">
                    <Button
                      icon={<RotateCcw aria-hidden className="button__icon" />}
                      onClick={this.reset}
                      variant="ghost"
                    >
                      {t("common.retry")}
                    </Button>
                    <Button
                      icon={<RefreshCw aria-hidden className="button__icon" />}
                      onClick={this.reload}
                      variant="primary"
                    >
                      {t("common.refresh")}
                    </Button>
                  </div>
                </section>
              </main>
            );
          }}
        </I18nContext.Consumer>
      );
    }
    return this.props.children;
  }
}
