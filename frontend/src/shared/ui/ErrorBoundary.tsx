import { Component, type ErrorInfo, type ReactNode } from "react";
import { RefreshCw, RotateCcw } from "lucide-react";

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
        <main className="error-boundary" role="alert">
          <section className="error-boundary__panel">
            <div>
              <p className="error-boundary__eyebrow">React runtime</p>
              <h1 className="error-boundary__title">界面发生错误</h1>
              <p className="error-boundary__body">当前页面遇到未捕获异常。可以先重试渲染，仍失败时刷新页面。</p>
            </div>
            <pre className="error-boundary__detail">{error.message}</pre>
            <div className="inline-actions">
              <Button icon={<RotateCcw aria-hidden className="button__icon" />} onClick={this.reset} variant="ghost">
                重试
              </Button>
              <Button icon={<RefreshCw aria-hidden className="button__icon" />} onClick={this.reload} variant="primary">
                刷新
              </Button>
            </div>
          </section>
        </main>
      );
    }
    return this.props.children;
  }
}
