import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

describe("App", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders the development page and reports a healthy backend", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue({ ok: true, json: async () => ({ status: "ok" }) }),
    );

    render(<App />);

    expect(
      screen.getByRole("heading", { name: /SIH26154/ }),
    ).toBeInTheDocument();
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Backend connected",
    );
  });

  it("reports when the backend is unavailable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("Network unavailable")),
    );

    render(<App />);

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Backend unavailable",
    );
  });
});
