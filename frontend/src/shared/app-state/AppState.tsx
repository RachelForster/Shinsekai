import { createContext, useContext, useMemo, useReducer } from "react";
import type { ReactNode } from "react";

interface AppState {
  density: "comfortable" | "compact";
  language: "zh_CN" | "en" | "ja";
}

type AppAction =
  | { type: "setDensity"; density: AppState["density"] }
  | { type: "setLanguage"; language: AppState["language"] };

interface AppStateContextValue {
  dispatch: React.Dispatch<AppAction>;
  state: AppState;
}

const initialState: AppState = {
  density: "compact",
  language: "zh_CN",
};

const AppStateContext = createContext<AppStateContextValue | null>(null);

function reducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case "setDensity":
      return { ...state, density: action.density };
    case "setLanguage":
      return { ...state, language: action.language };
    default:
      return state;
  }
}

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const value = useMemo(() => ({ dispatch, state }), [state]);

  return (
    <AppStateContext.Provider value={value}>
      <div data-density={state.density}>{children}</div>
    </AppStateContext.Provider>
  );
}

export function useAppState() {
  const value = useContext(AppStateContext);
  if (!value) {
    throw new Error("useAppState must be used inside AppStateProvider");
  }
  return value;
}
