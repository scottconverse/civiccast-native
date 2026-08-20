// Global test setup for the operator console.
//
// 1. testing-library's DOM cleanup after every test, so renders never leak into
//    the next test's document.body (vitest provides no global afterEach).
// 2. A working Web Storage, repaired when the host Node ships its own
//    `localStorage` global and jsdom's Storage never gets installed. See the
//    twin of this block in apps/installer/vitest.setup.ts for the full
//    explanation -- keep the two in step. On this suite the defect failed 26 of
//    621 tests on Node 25 while CI, on Node 20, was green.
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

afterEach(cleanup)

function storageIsUsable(candidate: unknown): boolean {
  if (!candidate || typeof candidate !== "object") {
    return false;
  }
  const s = candidate as Record<string, unknown>;
  return (
    typeof s.getItem === "function" &&
    typeof s.setItem === "function" &&
    typeof s.removeItem === "function" &&
    typeof s.clear === "function"
  );
}

function createStorage(): Storage {
  const entries = new Map<string, string>();
  const storage: Storage = {
    get length() {
      return entries.size;
    },
    key(index: number) {
      return Array.from(entries.keys())[index] ?? null;
    },
    getItem(key: string) {
      return entries.has(String(key)) ? (entries.get(String(key)) as string) : null;
    },
    setItem(key: string, value: string) {
      entries.set(String(key), String(value));
    },
    removeItem(key: string) {
      entries.delete(String(key));
    },
    clear() {
      entries.clear();
    }
  };
  return storage;
}

for (const name of ["localStorage", "sessionStorage"] as const) {
  if (storageIsUsable((globalThis as unknown as Record<string, unknown>)[name])) {
    continue;
  }
  const storage = createStorage();
  // Both bindings, because production code reads `window.localStorage` and
  // some libraries read the bare global; leaving them different would be a
  // worse trap than the bug this fixes.
  Object.defineProperty(globalThis, name, {
    configurable: true,
    writable: true,
    value: storage
  });
  if (typeof window !== "undefined" && window !== (globalThis as unknown)) {
    Object.defineProperty(window, name, {
      configurable: true,
      writable: true,
      value: storage
    });
  }
}
