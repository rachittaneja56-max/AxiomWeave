import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const healthResponse = {
  ok: true,
  status: 200,
  json: async () => ({ status: "ok" }),
};

const preparedRequest = {
  source_text: "The team will open a community garden on Saturday.",
  output_types: ["executive_summary", "linkedin_post", "presentation"],
  audience: "Local residents",
  tone: "Welcoming",
  language: "English",
  detail_level: "standard",
  objective: "Announce the opening",
  style: "Plain language",
};

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

function installWorkspaceFetch(fetchMock: ReturnType<typeof vi.fn>) {
  const delegateFetch = fetchMock as unknown as (
    input: RequestInfo | URL,
    init?: RequestInit,
  ) => Promise<unknown>;
  const routedFetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    if (input === "/api/auth/session") {
      return Promise.resolve(jsonResponse({ authenticated: true }));
    }
    return delegateFetch(input, init);
  });
  vi.stubGlobal("fetch", routedFetch);
}

async function renderAuthenticatedWorkspace() {
  render(<App />);
  await screen.findByRole("heading", { name: "Content transformation" });
}

function fillRequiredControls() {
  fireEvent.change(screen.getByLabelText("Text source"), {
    target: { value: preparedRequest.source_text },
  });
  fireEvent.change(screen.getByLabelText("Audience"), {
    target: { value: preparedRequest.audience },
  });
  fireEvent.change(screen.getByLabelText("Tone"), {
    target: { value: preparedRequest.tone },
  });
  fireEvent.change(screen.getByLabelText("Communication objective"), {
    target: { value: preparedRequest.objective },
  });
  fireEvent.change(screen.getByLabelText("Content style"), {
    target: { value: preparedRequest.style },
  });
}

function selectMultipleOutputs() {
  for (const output of ["Executive summary", "LinkedIn post", "Presentation"]) {
    fireEvent.click(screen.getByRole("checkbox", { name: output }));
  }
}

describe("transformation request form", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_GOOGLE_CLIENT_ID", "test-web-client");
    vi.stubGlobal("google", {
      accounts: {
        id: {
          initialize: vi.fn(),
          renderButton: vi.fn(),
        },
      },
    });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("renders the request controls and permits selecting multiple outputs", async () => {
    installWorkspaceFetch(vi.fn().mockResolvedValue(healthResponse));

    await renderAuthenticatedWorkspace();

    expect(
      screen.getByRole("heading", { name: "Content transformation" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Text source")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Paste text" })).toBeChecked();
    expect(
      screen.getByRole("radio", { name: "Upload text file" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Audience")).toBeInTheDocument();
    expect(screen.getByLabelText("Tone")).toBeInTheDocument();
    expect(screen.getByLabelText("Language")).toHaveValue("English");
    expect(screen.getByLabelText("Detail level")).toHaveValue("standard");
    expect(
      screen.getByLabelText("Communication objective"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Content style")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("checkbox", { name: "Executive summary" }),
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "LinkedIn post" }));

    expect(
      screen.getByRole("checkbox", { name: "Executive summary" }),
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "LinkedIn post" }),
    ).toBeChecked();
  });

  it("extracts a selected file and submits its canonical source text", async () => {
    const extractedSource = "A fictional report about a community garden.";
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(healthResponse)
      .mockResolvedValueOnce(
        jsonResponse({
          filename: "garden.md",
          media_type: "text/markdown",
          character_count: extractedSource.length,
          source_text: extractedSource,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "ready",
          request: { ...preparedRequest, source_text: extractedSource },
        }),
      );
    installWorkspaceFetch(fetchMock);

    await renderAuthenticatedWorkspace();
    fireEvent.click(screen.getByRole("radio", { name: "Upload text file" }));
    const file = new File([extractedSource], "garden.md", {
      type: "text/markdown",
    });
    fireEvent.change(screen.getByLabelText("Text file (.txt or .md)"), {
      target: { files: [file] },
    });

    await waitFor(() =>
      expect(
        screen
          .queryAllByRole("status")
          .some((status) => status.textContent?.includes("garden.md")),
      ).toBe(true),
    );
    expect(
      screen
        .getAllByRole("status")
        .find((status) => status.textContent?.includes("garden.md"))
        ?.textContent,
    ).toContain("44 characters");
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/sources/text-file",
      expect.objectContaining({ method: "POST", body: expect.any(FormData) }),
    );

    selectMultipleOutputs();
    fireEvent.click(screen.getByRole("button", { name: "Prepare request" }));
    expect(await screen.findByText("Request ready")).toBeInTheDocument();
    expect(
      JSON.parse(fetchMock.mock.calls[2][1].body as string).source_text,
    ).toBe(extractedSource);
  });

  it("shows extraction errors and rejects malformed successful responses", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(healthResponse)
      .mockResolvedValueOnce(
        jsonResponse(
          {
            error: {
              code: "invalid_encoding",
              message: "The file must contain valid UTF-8 text.",
            },
          },
          422,
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse({ filename: "bad.txt", source_text: "missing metadata" }),
      );
    installWorkspaceFetch(fetchMock);

    await renderAuthenticatedWorkspace();
    fireEvent.click(screen.getByRole("radio", { name: "Upload text file" }));
    const file = new File(["plain text"], "source.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("Text file (.txt or .md)"), {
      target: { files: [file] },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("valid UTF-8");

    fireEvent.change(screen.getByLabelText("Text file (.txt or .md)"), {
      target: { files: [file] },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "unexpected file extraction response",
    );
  });

  it("shows a safe message when file extraction cannot reach the backend", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(healthResponse)
      .mockRejectedValueOnce(new Error("private network detail"));
    installWorkspaceFetch(fetchMock);

    await renderAuthenticatedWorkspace();
    fireEvent.click(screen.getByRole("radio", { name: "Upload text file" }));
    const file = new File(["plain text"], "source.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("Text file (.txt or .md)"), {
      target: { files: [file] },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not reach the backend",
    );
    expect(
      screen.queryByText("private network detail"),
    ).not.toBeInTheDocument();
  });

  it("clears uploaded content when switching source modes", async () => {
    const extractedSource = "Uploaded source content";
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(healthResponse)
      .mockResolvedValueOnce(
        jsonResponse({
          filename: "source.txt",
          media_type: "text/plain",
          character_count: extractedSource.length,
          source_text: extractedSource,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ status: "ready", request: preparedRequest }),
      );
    installWorkspaceFetch(fetchMock);

    await renderAuthenticatedWorkspace();
    fireEvent.click(screen.getByRole("radio", { name: "Upload text file" }));
    const file = new File([extractedSource], "source.txt", {
      type: "text/plain",
    });
    fireEvent.change(screen.getByLabelText("Text file (.txt or .md)"), {
      target: { files: [file] },
    });
    await waitFor(() =>
      expect(
        screen
          .queryAllByRole("status")
          .some((status) => status.textContent?.includes("source.txt")),
      ).toBe(true),
    );
    fireEvent.click(screen.getByRole("radio", { name: "Paste text" }));
    expect(screen.getByLabelText("Text source")).toHaveValue("");

    selectMultipleOutputs();
    fireEvent.click(screen.getByRole("button", { name: "Prepare request" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Enter source text",
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("submits the canonical multi-output request and shows the ready state", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(healthResponse)
      .mockResolvedValueOnce(
        jsonResponse({ status: "ready", request: preparedRequest }),
      );
    installWorkspaceFetch(fetchMock);

    await renderAuthenticatedWorkspace();
    fillRequiredControls();
    selectMultipleOutputs();
    fireEvent.click(screen.getByRole("button", { name: "Prepare request" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Request ready",
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Content has not been generated",
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/transformations/prepare",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(preparedRequest),
      }),
    );
  });

  it("gives local feedback for missing source and output selection", async () => {
    const fetchMock = vi.fn().mockResolvedValue(healthResponse);
    installWorkspaceFetch(fetchMock);

    await renderAuthenticatedWorkspace();
    fireEvent.click(screen.getByRole("button", { name: "Prepare request" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Enter source text",
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);

    fireEvent.change(screen.getByLabelText("Text source"), {
      target: { value: "A fictional team announcement." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Prepare request" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Choose at least one output type",
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shows safe field feedback for backend validation failures", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(healthResponse)
      .mockResolvedValueOnce(
        jsonResponse(
          {
            error: {
              code: "invalid_request",
              message: "Request is invalid",
              fields: [{ field: "audience", message: "Value is too long" }],
            },
          },
          422,
        ),
      );
    installWorkspaceFetch(fetchMock);

    await renderAuthenticatedWorkspace();
    fillRequiredControls();
    selectMultipleOutputs();
    fireEvent.click(screen.getByRole("button", { name: "Prepare request" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Please review: Audience",
    );
    expect(screen.queryByText("Value is too long")).not.toBeInTheDocument();
  });

  it("handles a network failure without displaying backend details", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(healthResponse)
      .mockRejectedValueOnce(new Error("private network detail"));
    installWorkspaceFetch(fetchMock);

    await renderAuthenticatedWorkspace();
    fillRequiredControls();
    selectMultipleOutputs();
    fireEvent.click(screen.getByRole("button", { name: "Prepare request" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not reach the backend",
    );
    expect(
      screen.queryByText("private network detail"),
    ).not.toBeInTheDocument();
  });

  it("rejects an unexpected successful response shape", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(healthResponse)
      .mockResolvedValueOnce(jsonResponse({ status: "ready", request: {} }));
    installWorkspaceFetch(fetchMock);

    await renderAuthenticatedWorkspace();
    fillRequiredControls();
    selectMultipleOutputs();
    fireEvent.click(screen.getByRole("button", { name: "Prepare request" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "unexpected response",
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

describe("AxiomWeave sign-in", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  beforeEach(() => {
    vi.stubEnv("VITE_GOOGLE_CLIENT_ID", "configured-web-client");
  });

  it("keeps the workspace hidden while session state is unresolved", () => {
    let resolveSession:
      ((response: ReturnType<typeof jsonResponse>) => void) | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise((resolve) => {
            resolveSession = resolve;
          }),
      ),
    );
    render(<App />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Checking your AxiomWeave session",
    );
    expect(screen.queryByLabelText("Text source")).not.toBeInTheDocument();
    resolveSession?.(jsonResponse({ authenticated: false }, 401));
  });

  it("shows the product sign-in screen without password fields", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, 401)));
    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Sign in to AxiomWeave" }),
    ).toBeInTheDocument();
    expect(screen.getByText("AXIOMWEAVE")).toBeInTheDocument();
    expect(
      screen.getByText("One source. Many artifacts. Every claim traceable."),
    ).toBeInTheDocument();
    expect(screen.getByText("Multi-output transformation")).toBeInTheDocument();
    expect(screen.queryByLabelText(/email|password/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/forgot password/i)).not.toBeInTheDocument();
  });

  it("explains when the Google client ID is not configured", async () => {
    vi.stubEnv("VITE_GOOGLE_CLIENT_ID", "");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, 401)));
    render(<App />);

    expect(
      await screen.findByText(/Set SIH_GOOGLE_CLIENT_ID for local development/),
    ).toBeInTheDocument();
  });

  it("initializes GIS with the configured client ID and sends the callback credential", async () => {
    const initialize = vi.fn();
    const renderButton = vi.fn();
    vi.stubGlobal("google", { accounts: { id: { initialize, renderButton } } });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({}, 401))
      .mockResolvedValueOnce(jsonResponse({ authenticated: true }));
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findByRole("heading", { name: "Sign in to AxiomWeave" });
    await waitFor(() =>
      expect(initialize).toHaveBeenCalledWith(
        expect.objectContaining({ client_id: "configured-web-client" }),
      ),
    );
    expect(renderButton).toHaveBeenCalledWith(
      expect.any(HTMLElement),
      expect.objectContaining({ text: "continue_with" }),
    );
    const callback = initialize.mock.calls[0][0].callback as (response: {
      credential: string;
    }) => Promise<void>;
    await callback({ credential: "opaque-google-token" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/google",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        body: JSON.stringify({ credential: "opaque-google-token" }),
      }),
    );
    expect(
      await screen.findByRole("heading", { name: "Content transformation" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("opaque-google-token")).not.toBeInTheDocument();
  });

  it("shows a safe login error and returns to sign-in after logout", async () => {
    const initialize = vi.fn();
    vi.stubGlobal("google", {
      accounts: { id: { initialize, renderButton: vi.fn() } },
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({}, 401))
      .mockResolvedValueOnce(
        jsonResponse({ error: "private token detail" }, 401),
      )
      .mockResolvedValueOnce(jsonResponse({ authenticated: true }))
      .mockResolvedValueOnce(jsonResponse({ status: "ok" }))
      .mockResolvedValueOnce(jsonResponse({}, 204));
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    await screen.findByRole("heading", { name: "Sign in to AxiomWeave" });
    const callback = initialize.mock.calls[0][0].callback as (response: {
      credential: string;
    }) => Promise<void>;
    await callback({ credential: "sensitive-token-value" });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Sign-in could not be completed",
    );
    expect(screen.queryByText("sensitive-token-value")).not.toBeInTheDocument();

    fetchMock.mockResolvedValueOnce(jsonResponse({ authenticated: true }));
    await callback({ credential: "valid-token" });
    expect(
      await screen.findByRole("heading", { name: "Content transformation" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(
      await screen.findByRole("heading", { name: "Sign in to AxiomWeave" }),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/logout",
      expect.objectContaining({ method: "POST" }),
    );
    expect(screen.queryByLabelText("Text source")).not.toBeInTheDocument();
  });
});
