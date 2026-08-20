// Guarantee a working Web Storage in the jsdom test environment.
//
// Node 24+ ships its own global `localStorage` / `sessionStorage`. vitest's
// jsdom environment sees those globals already defined and leaves them alone,
// so `window.localStorage` ends up being Node's object rather than jsdom's
// Storage -- and reading a method off it fails:
//
//   TypeError: window.localStorage.clear is not a function
//
// That is an ENVIRONMENT defect, not a product one. It made 38 of 153 unit
// tests fail on a developer machine running Node 25 while CI, pinned to Node
// 20, saw 1 failure -- i.e. the local suite stopped being able to tell the
// truth about the code, in either direction.
//
// This installs a real Storage implementation when the environment's one is
// unusable. It matches the DOM spec's Storage semantics (string coercion,
// `length`, `key(i)`, null for a missing key) so a test that passes here
// passes in a browser. When jsdom's own Storage is present -- which is what
// happens on Node 20 and on any Node without built-in Web Storage -- this does
// nothing at all.
//
// Keep it until the repo's Node floor is above the divergence and CI and
// developer machines run the same major.

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
