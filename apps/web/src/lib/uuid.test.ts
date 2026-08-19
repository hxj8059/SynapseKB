import { afterEach, describe, expect, it, vi } from "vitest";

import { createClientUuid } from "./uuid";

const UUID_V4_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe("createClientUuid", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("uses the native implementation when available", () => {
    const expected = "71d26034-a4fe-4f4d-8af5-df9f9a047daf";
    const randomUUID = vi.fn(() => expected);
    vi.stubGlobal("crypto", { randomUUID });

    expect(createClientUuid()).toBe(expected);
    expect(randomUUID).toHaveBeenCalledOnce();
  });

  it("creates a UUID v4 when randomUUID is unavailable on HTTP", () => {
    const getRandomValues = vi.fn((bytes: Uint8Array) => {
      bytes.fill(0xff);
      return bytes;
    });
    vi.stubGlobal("crypto", { getRandomValues });

    const uuid = createClientUuid();

    expect(uuid).toMatch(UUID_V4_PATTERN);
    expect(uuid).toBe("ffffffff-ffff-4fff-bfff-ffffffffffff");
    expect(getRandomValues).toHaveBeenCalledOnce();
  });

  it("still creates a UI identifier in legacy browsers without Web Crypto", () => {
    vi.stubGlobal("crypto", undefined);
    vi.spyOn(Math, "random").mockReturnValue(0);

    expect(createClientUuid()).toBe("00000000-0000-4000-8000-000000000000");
  });
});
