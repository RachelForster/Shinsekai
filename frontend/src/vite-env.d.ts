/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SHINSEKAI_API_BASE?: string;
  readonly VITE_SHINSEKAI_BRIDGE_TOKEN?: string;
  readonly VITE_SHINSEKAI_TARGET?: string;
  readonly VITE_SHINSEKAI_STANDALONE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
