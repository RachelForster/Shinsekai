/**
 * Zero-dependency IndexedDB persistence layer for Shinsekai Standalone Runtime
 * (Bilibili Toy & Mobile Standalone Mode).
 *
 * Automatically falls back to an in-memory Map store in environments without
 * IndexedDB (e.g., SSR, Vitest Node environment, or restricted sandbox iframes).
 */

export const STANDALONE_DB_NAME = "shinsekai-standalone-v1";
export const STANDALONE_DB_VERSION = 1;

export type StandaloneStoreName = "kv_config" | "sessions" | "turn_nodes" | "compact_checkpoints" | "vfs_blobs";

export interface KvConfigRecord {
  key: string;
  value: unknown;
  updatedAtMs: number;
}

export interface VfsBlobRecord {
  path: string;
  blob: Blob;
  mimeType: string;
  size: number;
  updatedAtMs: number;
}

interface MemoryFallbackDb {
  kv_config: Map<string, KvConfigRecord>;
  sessions: Map<string, Record<string, unknown>>;
  turn_nodes: Map<string, Record<string, unknown>>;
  compact_checkpoints: Map<string, Record<string, unknown>>;
  vfs_blobs: Map<string, VfsBlobRecord>;
}

const memoryDb: MemoryFallbackDb = {
  kv_config: new Map(),
  sessions: new Map(),
  turn_nodes: new Map(),
  compact_checkpoints: new Map(),
  vfs_blobs: new Map(),
};

let dbPromise: Promise<IDBDatabase | null> | null = null;

function hasIndexedDb(): boolean {
  try {
    return typeof indexedDB !== "undefined" && indexedDB !== null;
  } catch {
    return false;
  }
}

export function openStandaloneDb(): Promise<IDBDatabase | null> {
  if (dbPromise) {
    return dbPromise;
  }
  if (!hasIndexedDb()) {
    dbPromise = Promise.resolve(null);
    return dbPromise;
  }

  dbPromise = new Promise<IDBDatabase | null>((resolve) => {
    try {
      const request = indexedDB.open(STANDALONE_DB_NAME, STANDALONE_DB_VERSION);

      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains("kv_config")) {
          db.createObjectStore("kv_config", { keyPath: "key" });
        }
        if (!db.objectStoreNames.contains("sessions")) {
          db.createObjectStore("sessions", { keyPath: "sessionId" });
        }
        if (!db.objectStoreNames.contains("turn_nodes")) {
          const turnStore = db.createObjectStore("turn_nodes", { keyPath: "nodeKey" });
          turnStore.createIndex("by_session", "sessionId", { unique: false });
          turnStore.createIndex("by_session_branch", ["sessionId", "branchId", "seq"], { unique: true });
        }
        if (!db.objectStoreNames.contains("compact_checkpoints")) {
          const cpStore = db.createObjectStore("compact_checkpoints", { keyPath: "checkpointKey" });
          cpStore.createIndex("by_session", "sessionId", { unique: false });
          cpStore.createIndex("by_session_branch", ["sessionId", "branchId", "upToSeq"], { unique: true });
        }
        if (!db.objectStoreNames.contains("vfs_blobs")) {
          db.createObjectStore("vfs_blobs", { keyPath: "path" });
        }
      };

      request.onsuccess = () => resolve(request.result);
      request.onerror = () => resolve(null);
      request.onblocked = () => resolve(null);
    } catch {
      resolve(null);
    }
  });

  return dbPromise;
}

function keyPathForStore(storeName: StandaloneStoreName): string {
  switch (storeName) {
    case "kv_config":
      return "key";
    case "sessions":
      return "sessionId";
    case "turn_nodes":
      return "nodeKey";
    case "compact_checkpoints":
      return "checkpointKey";
    case "vfs_blobs":
      return "path";
  }
}

function getMemoryMap(storeName: StandaloneStoreName): Map<string, unknown> {
  return memoryDb[storeName] as unknown as Map<string, unknown>;
}

export async function idbGet<T>(storeName: StandaloneStoreName, key: string): Promise<T | undefined> {
  const db = await openStandaloneDb();
  if (!db) {
    return getMemoryMap(storeName).get(key) as T | undefined;
  }
  return new Promise<T | undefined>((resolve) => {
    try {
      const tx = db.transaction(storeName, "readonly");
      const req = tx.objectStore(storeName).get(key);
      req.onsuccess = () => resolve((req.result as T | undefined) ?? undefined);
      req.onerror = () => resolve(getMemoryMap(storeName).get(key) as T | undefined);
    } catch {
      resolve(getMemoryMap(storeName).get(key) as T | undefined);
    }
  });
}

export async function idbGetAll<T>(storeName: StandaloneStoreName): Promise<T[]> {
  const db = await openStandaloneDb();
  if (!db) {
    return Array.from(getMemoryMap(storeName).values()) as T[];
  }
  return new Promise<T[]>((resolve) => {
    try {
      const tx = db.transaction(storeName, "readonly");
      const req = tx.objectStore(storeName).getAll();
      req.onsuccess = () => resolve((req.result as T[]) ?? []);
      req.onerror = () => resolve(Array.from(getMemoryMap(storeName).values()) as T[]);
    } catch {
      resolve(Array.from(getMemoryMap(storeName).values()) as T[]);
    }
  });
}

export async function idbPut<T extends object>(storeName: StandaloneStoreName, record: T): Promise<void> {
  const keyField = keyPathForStore(storeName);
  const recordKey = String((record as Record<string, unknown>)[keyField] ?? "");
  if (recordKey) {
    getMemoryMap(storeName).set(recordKey, record);
  }

  const db = await openStandaloneDb();
  if (!db) {
    return;
  }
  await new Promise<void>((resolve) => {
    try {
      const tx = db.transaction(storeName, "readwrite");
      tx.objectStore(storeName).put(record);
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
      tx.onabort = () => resolve();
    } catch {
      resolve();
    }
  });
}

export async function idbPutMany<T extends object>(storeName: StandaloneStoreName, records: T[]): Promise<void> {
  if (!records.length) {
    return;
  }
  const keyField = keyPathForStore(storeName);
  const mem = getMemoryMap(storeName);
  for (const record of records) {
    const recordKey = String((record as Record<string, unknown>)[keyField] ?? "");
    if (recordKey) {
      mem.set(recordKey, record);
    }
  }

  const db = await openStandaloneDb();
  if (!db) {
    return;
  }
  await new Promise<void>((resolve) => {
    try {
      const tx = db.transaction(storeName, "readwrite");
      const store = tx.objectStore(storeName);
      for (const record of records) {
        store.put(record);
      }
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
      tx.onabort = () => resolve();
    } catch {
      resolve();
    }
  });
}

export async function idbDelete(storeName: StandaloneStoreName, key: string): Promise<void> {
  getMemoryMap(storeName).delete(key);
  const db = await openStandaloneDb();
  if (!db) {
    return;
  }
  await new Promise<void>((resolve) => {
    try {
      const tx = db.transaction(storeName, "readwrite");
      tx.objectStore(storeName).delete(key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
      tx.onabort = () => resolve();
    } catch {
      resolve();
    }
  });
}

export async function idbDeleteMany(storeName: StandaloneStoreName, keys: string[]): Promise<void> {
  if (!keys.length) {
    return;
  }
  const mem = getMemoryMap(storeName);
  for (const key of keys) {
    mem.delete(key);
  }
  const db = await openStandaloneDb();
  if (!db) {
    return;
  }
  await new Promise<void>((resolve) => {
    try {
      const tx = db.transaction(storeName, "readwrite");
      const store = tx.objectStore(storeName);
      for (const key of keys) {
        store.delete(key);
      }
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
      tx.onabort = () => resolve();
    } catch {
      resolve();
    }
  });
}

export async function getKvConfig<T>(key: string): Promise<T | undefined> {
  const rec = await idbGet<KvConfigRecord>("kv_config", key);
  return rec ? (rec.value as T) : undefined;
}

export async function setKvConfig<T>(key: string, value: T): Promise<void> {
  await idbPut<KvConfigRecord>("kv_config", {
    key,
    value,
    updatedAtMs: Date.now(),
  });
}

export async function clearAllStandaloneStorage(): Promise<void> {
  for (const storeName of [
    "kv_config",
    "sessions",
    "turn_nodes",
    "compact_checkpoints",
    "vfs_blobs",
  ] as StandaloneStoreName[]) {
    getMemoryMap(storeName).clear();
  }
  const db = await openStandaloneDb();
  if (!db) {
    return;
  }
  await new Promise<void>((resolve) => {
    try {
      const tx = db.transaction(
        ["kv_config", "sessions", "turn_nodes", "compact_checkpoints", "vfs_blobs"],
        "readwrite",
      );
      for (const storeName of tx.objectStoreNames) {
        tx.objectStore(storeName).clear();
      }
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
      tx.onabort = () => resolve();
    } catch {
      resolve();
    }
  });
}
