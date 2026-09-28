import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
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
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders the request controls and permits selecting multiple outputs", () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(healthResponse));

    render(<App />);

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
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
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
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
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
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
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
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
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
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
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
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
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
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
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
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
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
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    fillRequiredControls();
    selectMultipleOutputs();
    fireEvent.click(screen.getByRole("button", { name: "Prepare request" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "unexpected response",
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
