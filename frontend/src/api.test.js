import { describe, it, expect, vi, beforeEach } from "vitest";

// In-memory localStorage for the swrCache dependency (vitest runs in node env).
const store = new Map();
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
  key: (i) => [...store.keys()][i] ?? null,
  get length() { return store.size; },
};

const jsonResponse = (body) => ({
  ok: true,
  status: 200,
  headers: { get: () => "0" },
  json: async () => body,
});

describe("getJson backend-error handling", () => {
  beforeEach(() => { store.clear(); vi.restoreAllMocks(); });

  it("exposes data.error as meta.backendError and does not cache it", async () => {
    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ error: "ExpiredToken: please re-auth", total_mtd: 0 }))
      .mockResolvedValueOnce(jsonResponse({ total_mtd: 42 }));
    const { api } = await import("./api");

    const first = await api.summary("default", "mtd");
    expect(first.meta.backendError).toBe("ExpiredToken: please re-auth");

    // Second call must NOT be served from cache (error payload was not cached).
    const second = await api.summary("default", "mtd");
    expect(second.data.total_mtd).toBe(42);
    expect(second.meta.backendError).toBeNull();
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
  });

  it("caches clean payloads as before", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(jsonResponse({ total_mtd: 7 }));
    const { api } = await import("./api");
    await api.summary("p", "mtd");
    const again = await api.summary("p", "mtd");
    expect(again.meta.fromCache).toBe("fresh");
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });
});
