import { afterEach, describe, expect, it, vi } from "vitest";

import { copyText } from "./clipboard";

const secureContextDescriptor = Object.getOwnPropertyDescriptor(window, "isSecureContext");

function setSecureContext(value: boolean) {
  Object.defineProperty(window, "isSecureContext", { configurable: true, value });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  if (secureContextDescriptor) {
    Object.defineProperty(window, "isSecureContext", secureContextDescriptor);
  } else {
    Reflect.deleteProperty(window, "isSecureContext");
  }
  Reflect.deleteProperty(document, "execCommand");
});

describe("copyText", () => {
  it("uses the Clipboard API in a secure context", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setSecureContext(true);
    vi.stubGlobal("navigator", { clipboard: { writeText } });

    await copyText("skbp_secret");

    expect(writeText).toHaveBeenCalledWith("skbp_secret");
  });

  it("falls back to execCommand when served over HTTP", async () => {
    const execCommand = vi.fn(() => true);
    setSecureContext(false);
    Object.defineProperty(document, "execCommand", { configurable: true, value: execCommand });

    await copyText("skbp_http_token");

    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(document.querySelector("textarea")).toBeNull();
  });

  it("returns an actionable error when both copy mechanisms are unavailable", async () => {
    setSecureContext(false);

    await expect(copyText("skbp_manual_copy")).rejects.toThrow("手动选择并复制令牌");
    expect(document.querySelector("textarea")).toBeNull();
  });
});
