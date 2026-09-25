import { invoke } from "@tauri-apps/api/core";

export const getAutostart = () => invoke<boolean>("desktop_autostart_get");
export const setAutostart = (enabled: boolean) => invoke<boolean>("desktop_autostart_set", { enabled });
