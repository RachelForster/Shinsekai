import { useCallback, useState } from "react";

const recentInputLimit = 3;

export function useRecentUserInputs() {
  const [recentInputs, setRecentInputs] = useState<string[]>([]);

  const rememberInput = useCallback((value: string) => {
    const input = value.trim();
    if (!input) {
      return;
    }
    setRecentInputs((current) => [input, ...current].slice(0, recentInputLimit));
  }, []);

  return { recentInputs, rememberInput };
}
