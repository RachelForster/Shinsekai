import { ArrowLeft, LoaderCircle, Paintbrush, Play, Plus, RefreshCw, Save } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type RefObject } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { useI18n } from "../../shared/i18n";

type PrimaryActionKind = "add" | "customize" | "play" | "refresh" | "save";

interface TopBarConfig {
  actionKind: PrimaryActionKind;
  backLabel?: string;
  backTo?: string;
  conciseLabel?: string;
  primarySelector: string;
  title: string;
}

interface PrimaryActionState {
  disabled: boolean;
  label: string;
  loading: boolean;
  present: boolean;
}

const EMPTY_ACTION_STATE: PrimaryActionState = {
  disabled: false,
  label: "",
  loading: false,
  present: false,
};

function useIsMobileViewport() {
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia("(max-width: 760px)").matches
      : false,
  );

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const mql = window.matchMedia("(max-width: 760px)");
    const update = () => setIsMobile(mql.matches);
    update();
    if (typeof mql.addEventListener === "function") {
      mql.addEventListener("change", update);
      return () => mql.removeEventListener("change", update);
    }
    mql.addListener(update);
    return () => mql.removeListener(update);
  }, []);

  return isMobile;
}

function renderActionIcon(kind: PrimaryActionKind) {
  switch (kind) {
    case "add":
      return <Plus aria-hidden className="button__icon" />;
    case "customize":
      return <Paintbrush aria-hidden className="button__icon" />;
    case "play":
      return <Play aria-hidden className="button__icon" />;
    case "refresh":
      return <RefreshCw aria-hidden className="button__icon" />;
    case "save":
      return <Save aria-hidden className="button__icon" />;
  }
}

export function MobileTopAppBar({ outletRef }: { outletRef: RefObject<HTMLElement | null> }) {
  const isMobile = useIsMobileViewport();
  const location = useLocation();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { t } = useI18n();

  const routeKey = `${location.pathname}${location.search}`;

  const config = useMemo<TopBarConfig>(() => {
    const pathname = location.pathname;

    if (pathname.startsWith("/settings/templates")) {
      const conversationId = params.get("conversation");
      const configuring =
        params.get("tab") === "new" || Boolean(conversationId) || (!params.has("tab") && params.has("mode"));
      if (configuring) {
        return {
          actionKind: conversationId ? "save" : "play",
          backLabel: t("conversation.workspace"),
          backTo: "/settings/templates?tab=recent",
          conciseLabel: conversationId ? t("common.save") : undefined,
          primarySelector: ".template-page__footer .button--primary",
          title: conversationId ? t("conversation.settings") : t("conversation.new"),
        };
      }
      return {
        actionKind: "add",
        conciseLabel: t("conversation.new"),
        primarySelector:
          ".conversation-library__header .button--primary, .conversation-library__empty .button--primary",
        title: t("nav.template"),
      };
    }

    if (pathname.startsWith("/settings/characters")) {
      return {
        actionKind: "save",
        conciseLabel: t("common.save"),
        primarySelector: ".character-page__header .button--primary",
        title: t("character.title"),
      };
    }

    if (pathname.startsWith("/settings/api")) {
      return {
        actionKind: "save",
        conciseLabel: t("common.save"),
        primarySelector: ".api-page__header .button--primary",
        title: t("api.title"),
      };
    }

    if (pathname.startsWith("/settings/backgrounds")) {
      return {
        actionKind: "save",
        conciseLabel: t("common.save"),
        primarySelector: ".background-page__header .button--primary",
        title: t("background.title"),
      };
    }

    if (pathname.startsWith("/settings/effects")) {
      return {
        actionKind: "save",
        conciseLabel: t("common.save"),
        primarySelector: ".effect-page__header .button--primary",
        title: t("effect.title"),
      };
    }

    if (pathname.startsWith("/settings/system/chat-themes/customize")) {
      return {
        actionKind: "save",
        backLabel: t("chat.theme.customizer.back"),
        backTo: "/settings/system/chat-themes",
        conciseLabel: t("common.save"),
        primarySelector: ".chat-theme-customizer-page__header .button--primary",
        title: t("chat.theme.customizer.title"),
      };
    }

    if (pathname.startsWith("/settings/system/chat-themes")) {
      return {
        actionKind: "customize",
        backLabel: t("chat.theme.backToSettings"),
        backTo: "/settings/system",
        primarySelector: ".chat-theme-management-page__header .button--primary",
        title: t("chat.theme.title"),
      };
    }

    if (pathname.startsWith("/settings/system")) {
      return {
        actionKind: "save",
        conciseLabel: t("common.save"),
        primarySelector: ".system-page > .page__header .button--primary",
        title: t("system.title"),
      };
    }

    if (pathname.startsWith("/settings/logs")) {
      return {
        actionKind: "refresh",
        primarySelector: ".logs-header__actions .button--primary",
        title: t("nav.logs"),
      };
    }

    return {
      actionKind: "save",
      primarySelector: ".page__header .button--primary",
      title: t("app.title"),
    };
  }, [location.pathname, params, t]);

  const [actionState, setActionState] = useState<PrimaryActionState>(EMPTY_ACTION_STATE);

  const syncPrimaryAction = useCallback(() => {
    const outlet = outletRef.current;
    if (!outlet) {
      setActionState(EMPTY_ACTION_STATE);
      return;
    }
    const target = outlet.querySelector<HTMLButtonElement>(config.primarySelector);
    if (!target) {
      setActionState((prev) => (prev.present ? EMPTY_ACTION_STATE : prev));
      return;
    }
    const rawLabel =
      config.conciseLabel ??
      (target.querySelector(".button__label")?.textContent ?? target.textContent ?? "").trim();
    const loading = Boolean(target.querySelector(".button__spinner"));
    const disabled = target.disabled;

    setActionState((prev) => {
      if (
        prev.present &&
        prev.disabled === disabled &&
        prev.loading === loading &&
        prev.label === rawLabel
      ) {
        return prev;
      }
      return {
        disabled,
        label: rawLabel,
        loading,
        present: true,
      };
    });
  }, [config.conciseLabel, config.primarySelector, outletRef]);

  useEffect(() => {
    if (!isMobile) {
      return;
    }
    const outlet = outletRef.current;
    if (!outlet) {
      return;
    }

    syncPrimaryAction();
    const rafId = window.requestAnimationFrame(syncPrimaryAction);
    const observer = new MutationObserver(() => {
      syncPrimaryAction();
    });
    observer.observe(outlet, {
      attributes: true,
      characterData: true,
      childList: true,
      subtree: true,
    });

    return () => {
      window.cancelAnimationFrame(rafId);
      observer.disconnect();
    };
  }, [isMobile, outletRef, routeKey, syncPrimaryAction]);

  if (!isMobile) {
    return null;
  }

  const handlePrimaryClick = () => {
    const target = outletRef.current?.querySelector<HTMLButtonElement>(config.primarySelector);
    target?.click();
  };

  return (
    <header className="m3-top-app-bar">
      <div className="m3-top-app-bar__side m3-top-app-bar__side--start">
        {config.backTo ? (
          <button
            aria-label={config.backLabel ?? t("common.close")}
            className="icon-button m3-top-app-bar__back"
            onClick={() => navigate(config.backTo!)}
            type="button"
          >
            <ArrowLeft aria-hidden className="icon-button__icon" />
          </button>
        ) : null}
      </div>
      <h1 className="m3-top-app-bar__title">{config.title}</h1>
      <div className="m3-top-app-bar__side m3-top-app-bar__side--end">
        {actionState.present ? (
          <button
            className="button button--primary m3-top-app-bar__action"
            disabled={actionState.disabled}
            onClick={handlePrimaryClick}
            type="button"
          >
            {actionState.loading ? (
              <LoaderCircle aria-hidden className="button__spinner" />
            ) : (
              renderActionIcon(config.actionKind)
            )}
            <span className="button__label">{actionState.label}</span>
          </button>
        ) : null}
      </div>
    </header>
  );
}
