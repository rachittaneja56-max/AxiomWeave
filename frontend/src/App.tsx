import { useEffect, useRef, useState, type FormEvent } from "react";

const OUTPUT_TYPES = [
  { value: "executive_summary", label: "Executive summary" },
  { value: "linkedin_post", label: "LinkedIn post" },
  { value: "x_post", label: "X post" },
  { value: "advisory", label: "Advisory" },
  { value: "presentation", label: "Presentation" },
  { value: "infographic", label: "Infographic" },
  { value: "video_package", label: "Video package" },
] as const;

type OutputType = (typeof OUTPUT_TYPES)[number]["value"];
type DetailLevel = "brief" | "standard" | "detailed";

type TransformationRequest = {
  source_text: string;
  output_types: OutputType[];
  audience: string;
  tone: string;
  language: string;
  detail_level: DetailLevel;
  objective: string;
  style: string;
};

type PreparedRequest = {
  status: "ready";
  request: TransformationRequest;
};

type HealthState = "loading" | "online" | "offline";
type SourceMode = "paste" | "upload";

type SourceFileMetadata = {
  filename: string;
  character_count: number;
};

const SOURCE_TEXT_MAX_LENGTH = 20_000;

function sourceCharacterCount(sourceText: string): number {
  return Array.from(sourceText).length;
}

const INITIAL_REQUEST: TransformationRequest = {
  source_text: "",
  output_types: [],
  audience: "General public",
  tone: "Clear and informative",
  language: "English",
  detail_level: "standard",
  objective: "Inform the audience",
  style: "Plain language",
};

const FIELD_LABELS: Record<string, string> = {
  source_text: "Source text",
  output_types: "Output types",
  audience: "Audience",
  tone: "Tone",
  language: "Language",
  detail_level: "Detail level",
  objective: "Communication objective",
  style: "Content style",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPreparedRequest(value: unknown): value is PreparedRequest {
  if (
    !isRecord(value) ||
    value.status !== "ready" ||
    !isRecord(value.request)
  ) {
    return false;
  }

  const request = value.request;
  return (
    typeof request.source_text === "string" &&
    Array.isArray(request.output_types) &&
    request.output_types.length > 0 &&
    request.output_types.every((outputType: unknown) =>
      OUTPUT_TYPES.some((option) => option.value === outputType),
    ) &&
    typeof request.audience === "string" &&
    typeof request.tone === "string" &&
    typeof request.language === "string" &&
    (request.detail_level === "brief" ||
      request.detail_level === "standard" ||
      request.detail_level === "detailed") &&
    typeof request.objective === "string" &&
    typeof request.style === "string"
  );
}

function isExtractedText(value: unknown): value is {
  filename: string;
  media_type: "text/plain" | "text/markdown";
  character_count: number;
  source_text: string;
} {
  return (
    isRecord(value) &&
    typeof value.filename === "string" &&
    (value.media_type === "text/plain" ||
      value.media_type === "text/markdown") &&
    typeof value.source_text === "string" &&
    value.source_text.trim().length > 0 &&
    sourceCharacterCount(value.source_text) <= SOURCE_TEXT_MAX_LENGTH &&
    Number.isInteger(value.character_count) &&
    value.character_count === sourceCharacterCount(value.source_text)
  );
}

function extractionError(body: unknown, status: number): string {
  const message =
    isRecord(body) && isRecord(body.error) ? body.error.message : null;
  if (typeof message === "string") return message;
  if (status === 413)
    return "The file is too large. Choose a file up to 80 KiB.";
  if (status === 415)
    return "Unsupported file. Choose a .txt or .md text file.";
  if (status === 422)
    return "The file must contain non-empty UTF-8 text within the source limit.";
  return "The file could not be extracted. Please try again.";
}

function validationMessage(body: unknown): string {
  if (!isRecord(body) || !isRecord(body.error)) {
    return "The request did not pass backend validation. Review the fields and try again.";
  }

  const fields = body.error.fields;
  if (!Array.isArray(fields)) {
    return "The request did not pass backend validation. Review the fields and try again.";
  }

  const labels = fields
    .map((item: unknown) => {
      if (!isRecord(item) || typeof item.field !== "string") return null;
      const field = item.field.split(".")[0];
      return FIELD_LABELS[field] ?? null;
    })
    .filter((label): label is string => label !== null);

  if (labels.length === 0) {
    return "The request did not pass backend validation. Review the fields and try again.";
  }

  return `Please review: ${[...new Set(labels)].join(", ")}.`;
}

function Workspace({ onLogout }: { onLogout: () => void }) {
  const [health, setHealth] = useState<HealthState>("loading");
  const [request, setRequest] =
    useState<TransformationRequest>(INITIAL_REQUEST);
  const [sourceMode, setSourceMode] = useState<SourceMode>("paste");
  const [sourceFile, setSourceFile] = useState<SourceFileMetadata | null>(null);
  const [isExtracting, setIsExtracting] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [prepared, setPrepared] = useState<PreparedRequest | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    async function checkHealth() {
      try {
        const response = await fetch("/api/health", {
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("Health check failed");
        const body: unknown = await response.json();
        if (!isRecord(body) || body.status !== "ok") {
          throw new Error("Invalid health response");
        }
        setHealth("online");
      } catch {
        if (!controller.signal.aborted) setHealth("offline");
      }
    }

    void checkHealth();
    return () => controller.abort();
  }, []);

  function updateRequest<K extends keyof TransformationRequest>(
    field: K,
    value: TransformationRequest[K],
  ) {
    setRequest((current) => ({ ...current, [field]: value }));
    setError(null);
    setPrepared(null);
  }

  function toggleOutput(outputType: OutputType, checked: boolean) {
    const outputTypes = checked
      ? [...request.output_types, outputType]
      : request.output_types.filter((item) => item !== outputType);
    updateRequest("output_types", outputTypes);
  }

  function switchSourceMode(mode: SourceMode) {
    setSourceMode(mode);
    setRequest((current) => ({ ...current, source_text: "" }));
    setSourceFile(null);
    setError(null);
    setPrepared(null);
  }

  async function extractSourceFile(file: File | undefined) {
    if (!file) return;
    setError(null);
    setPrepared(null);
    setSourceFile(null);
    setRequest((current) => ({ ...current, source_text: "" }));
    setIsExtracting(true);

    try {
      const formData = new FormData();
      formData.append("file", file);
      const response = await fetch("/api/sources/text-file", {
        method: "POST",
        credentials: "include",
        body: formData,
      });
      let body: unknown;
      try {
        body = await response.json();
      } catch {
        setError("The backend returned an unreadable extraction response.");
        return;
      }

      if (!response.ok) {
        setError(extractionError(body, response.status));
        return;
      }

      if (!isExtractedText(body)) {
        setError(
          "The backend returned an unexpected file extraction response.",
        );
        return;
      }

      setRequest((current) => ({ ...current, source_text: body.source_text }));
      setSourceFile({
        filename: body.filename,
        character_count: body.character_count,
      });
    } catch {
      setError(
        "Could not reach the backend to extract this file. Check the connection and try again.",
      );
    } finally {
      setIsExtracting(false);
    }
  }

  async function submitRequest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPrepared(null);

    if (!request.source_text.trim()) {
      setError("Enter source text before preparing the request.");
      return;
    }

    if (request.output_types.length === 0) {
      setError("Choose at least one output type.");
      return;
    }

    setError(null);
    setIsSubmitting(true);

    try {
      const response = await fetch("/api/transformations/prepare", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      });

      let body: unknown;
      try {
        body = await response.json();
      } catch {
        setError("The backend returned an unreadable response. Please retry.");
        return;
      }

      if (response.status === 422) {
        setError(validationMessage(body));
        return;
      }

      if (!response.ok) {
        setError(
          `The request could not be prepared (HTTP ${response.status}). Please retry.`,
        );
        return;
      }

      if (!isPreparedRequest(body)) {
        setError(
          "The backend returned an unexpected response. The request was not marked ready.",
        );
        return;
      }

      setPrepared(body);
    } catch {
      setError(
        "Could not reach the backend. Check the connection and try again.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  const healthText = {
    loading: "Checking backend",
    online: "Backend connected",
    offline: "Backend unavailable",
  }[health];

  return (
    <main className="page-shell">
      <header className="page-header">
        <div>
          <p className="eyebrow">AXIOMWEAVE</p>
          <p className="eyebrow">Smart India Hackathon 2026 · NTRO</p>
          <h1>Content transformation</h1>
          <p className="intro">
            Prepare one source and choose the communication materials you need.
          </p>
        </div>
        <div className="workspace-header-actions">
          <div className={`health health--${health}`} aria-live="polite">
            <span className="health-dot" aria-hidden="true" />
            {healthText}
          </div>
          <button type="button" className="button-secondary" onClick={onLogout}>
            Sign out
          </button>
        </div>
      </header>

      <form className="request-form" onSubmit={submitRequest} noValidate>
        <section
          className="form-section source-section"
          aria-labelledby="source-heading"
        >
          <div className="section-heading">
            <span className="step-number" aria-hidden="true">
              1
            </span>
            <div>
              <h2 id="source-heading">Source content</h2>
              <p>Paste text or upload a lightweight text document.</p>
            </div>
          </div>
          <fieldset className="source-modes">
            <legend className="visually-hidden">Source mode</legend>
            <label>
              <input
                type="radio"
                name="source_mode"
                value="paste"
                checked={sourceMode === "paste"}
                disabled={isExtracting}
                onChange={() => switchSourceMode("paste")}
              />
              Paste text
            </label>
            <label>
              <input
                type="radio"
                name="source_mode"
                value="upload"
                checked={sourceMode === "upload"}
                disabled={isExtracting}
                onChange={() => switchSourceMode("upload")}
              />
              Upload text file
            </label>
          </fieldset>
          {sourceMode === "paste" ? (
            <>
              <label htmlFor="source-text">Text source</label>
              <textarea
                id="source-text"
                rows={8}
                value={request.source_text}
                onChange={(event) => {
                  setSourceFile(null);
                  updateRequest("source_text", event.target.value);
                }}
                placeholder="Paste or write your source text here"
              />
            </>
          ) : (
            <div className="upload-source">
              <label htmlFor="source-file">Text file (.txt or .md)</label>
              <input
                id="source-file"
                type="file"
                accept=".txt,.md,text/plain,text/markdown"
                onChange={(event) =>
                  void extractSourceFile(event.target.files?.[0])
                }
                disabled={isExtracting}
              />
              <p className="field-hint">
                UTF-8 text only. Maximum file size: 80 KiB.
              </p>
              {isExtracting && <p role="status">Extracting text file…</p>}
              {sourceFile && (
                <p className="field-hint" role="status">
                  {sourceFile.filename} ·{" "}
                  {sourceFile.character_count.toLocaleString()} characters
                </p>
              )}
            </div>
          )}
          <p className="field-hint">
            Text only. Source content is used for this request and is not saved.
          </p>
        </section>

        <section className="form-section" aria-labelledby="outputs-heading">
          <div className="section-heading">
            <span className="step-number" aria-hidden="true">
              2
            </span>
            <div>
              <h2 id="outputs-heading">Requested materials</h2>
              <p>Select one or more. All use the same source and settings.</p>
            </div>
          </div>
          <fieldset className="output-options">
            <legend className="visually-hidden">Output types</legend>
            {OUTPUT_TYPES.map((output) => (
              <label className="output-option" key={output.value}>
                <input
                  type="checkbox"
                  name="output_types"
                  value={output.value}
                  checked={request.output_types.includes(output.value)}
                  onChange={(event) =>
                    toggleOutput(output.value, event.target.checked)
                  }
                />
                <span>{output.label}</span>
              </label>
            ))}
          </fieldset>
        </section>

        <section
          className="form-section settings-section"
          aria-labelledby="settings-heading"
        >
          <div className="section-heading">
            <span className="step-number" aria-hidden="true">
              3
            </span>
            <div>
              <h2 id="settings-heading">Communication settings</h2>
              <p>Describe who this is for and how it should communicate.</p>
            </div>
          </div>
          <div className="settings-grid">
            <div className="field">
              <label htmlFor="audience">Audience</label>
              <input
                id="audience"
                value={request.audience}
                onChange={(event) =>
                  updateRequest("audience", event.target.value)
                }
              />
            </div>
            <div className="field">
              <label htmlFor="tone">Tone</label>
              <input
                id="tone"
                value={request.tone}
                onChange={(event) => updateRequest("tone", event.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="language">Language</label>
              <input
                id="language"
                value={request.language}
                onChange={(event) =>
                  updateRequest("language", event.target.value)
                }
              />
            </div>
            <div className="field">
              <label htmlFor="detail-level">Detail level</label>
              <select
                id="detail-level"
                value={request.detail_level}
                onChange={(event) =>
                  updateRequest(
                    "detail_level",
                    event.target.value as DetailLevel,
                  )
                }
              >
                <option value="brief">Brief</option>
                <option value="standard">Standard</option>
                <option value="detailed">Detailed</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="objective">Communication objective</label>
              <input
                id="objective"
                value={request.objective}
                onChange={(event) =>
                  updateRequest("objective", event.target.value)
                }
              />
            </div>
            <div className="field">
              <label htmlFor="style">Content style</label>
              <input
                id="style"
                value={request.style}
                onChange={(event) => updateRequest("style", event.target.value)}
              />
            </div>
          </div>
        </section>

        <div className="submit-row">
          <p className="generation-note">
            This prepares and validates your request. It does not generate
            content.
          </p>
          <button type="submit" disabled={isSubmitting || isExtracting}>
            {isSubmitting ? "Preparing…" : "Prepare request"}
          </button>
        </div>

        {error && (
          <p className="form-message form-message--error" role="alert">
            {error}
          </p>
        )}
        {prepared && (
          <div className="form-message form-message--success" role="status">
            <strong>Request ready</strong>
            <span>
              Validated for {prepared.request.output_types.length} requested{" "}
              {prepared.request.output_types.length === 1
                ? "material"
                : "materials"}
              . Content has not been generated.
            </span>
          </div>
        )}
      </form>
    </main>
  );
}

type AuthState = "loading" | "signed_out" | "signed_in";

const initializedGoogleApis = new WeakMap<object, string>();

function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const buttonContainer = useRef<HTMLDivElement>(null);
  const [message, setMessage] = useState<string | null>(null);
  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;

  useEffect(() => {
    if (!clientId) return;
    let mounted = true;
    let script: HTMLScriptElement | null = null;

    const initialize = () => {
      if (!mounted || !window.google || !buttonContainer.current) return;
      const googleId = window.google.accounts.id;
      if (initializedGoogleApis.get(googleId) !== clientId) {
        googleId.initialize({
          client_id: clientId,
          callback: async (response) => {
            const credential = response.credential;
            if (!credential) {
              setMessage(
                "Google sign-in did not return a credential. Please try again.",
              );
              return;
            }
            setMessage(null);
            try {
              const result = await fetch("/api/auth/google", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "include",
                body: JSON.stringify({ credential }),
              });
              if (!result.ok) {
                setMessage("Sign-in could not be completed. Please try again.");
                return;
              }
              const body: unknown = await result.json();
              if (!isRecord(body) || body.authenticated !== true) {
                setMessage(
                  "Sign-in returned an unexpected response. Please try again.",
                );
                return;
              }
              onSignedIn();
            } catch {
              setMessage(
                "Could not reach AxiomWeave. Check the connection and try again.",
              );
            }
          },
        });
        initializedGoogleApis.set(googleId, clientId);
      }
      buttonContainer.current.replaceChildren();
      googleId.renderButton(buttonContainer.current, {
        theme: "outline",
        size: "large",
        text: "continue_with",
        width: 280,
      });
    };

    if (window.google) {
      initialize();
    } else {
      script = document.querySelector<HTMLScriptElement>(
        "#google-identity-services",
      );
      if (!script) {
        script = document.createElement("script");
        script.id = "google-identity-services";
        script.src = "https://accounts.google.com/gsi/client";
        script.async = true;
        script.defer = true;
        script.addEventListener("load", initialize, { once: true });
        script.addEventListener(
          "error",
          () => {
            if (mounted)
              setMessage(
                "Google sign-in could not load. Check your connection and configuration, then refresh to retry.",
              );
          },
          { once: true },
        );
        document.head.append(script);
      } else {
        script.addEventListener("load", initialize, { once: true });
      }
    }

    return () => {
      mounted = false;
      script?.removeEventListener("load", initialize);
    };
  }, [clientId, onSignedIn]);

  return (
    <main className="signin-shell">
      <section className="signin-story" aria-labelledby="product-name">
        <p className="signin-kicker">Source-grounded communication</p>
        <p className="signin-brand">AXIOMWEAVE</p>
        <h1 id="product-name">
          Source-Grounded Content Transformation Workspace
        </h1>
        <p className="signin-tagline">
          One source. Many artifacts. Every claim traceable.
        </p>
        <p className="signin-description">
          Transform one authoritative source into traceable, reviewable
          communication artifacts.
        </p>
        <ul className="signin-benefits">
          <li>Multi-output transformation</li>
          <li>Source-linked evidence</li>
          <li>Version-aware review</li>
        </ul>
      </section>
      <section className="signin-card" aria-labelledby="signin-heading">
        <p className="eyebrow">AxiomWeave</p>
        <h2 id="signin-heading">Sign in to AxiomWeave</h2>
        {clientId ? (
          <div
            ref={buttonContainer}
            className="google-button"
            aria-label="Continue with Google"
          />
        ) : (
          <p className="signin-message" role="status">
            Google sign-in is not configured. Set SIH_GOOGLE_CLIENT_ID for local
            development.
          </p>
        )}
        {message && (
          <p className="signin-message" role="alert">
            {message}
          </p>
        )}
      </section>
    </main>
  );
}

export default function App() {
  const [authState, setAuthState] = useState<AuthState>("loading");

  useEffect(() => {
    let mounted = true;
    void fetch("/api/auth/session", { credentials: "include" })
      .then(async (response) => {
        if (!mounted) return;
        if (response.status === 401) {
          setAuthState("signed_out");
          return;
        }
        if (!response.ok) throw new Error("session unavailable");
        const body: unknown = await response.json();
        setAuthState(
          isRecord(body) && body.authenticated === true
            ? "signed_in"
            : "signed_out",
        );
      })
      .catch(() => {
        if (mounted) setAuthState("signed_out");
      });
    return () => {
      mounted = false;
    };
  }, []);

  async function signOut() {
    try {
      await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "include",
      });
    } catch {
      // Clear the local workspace view even when the network is unavailable.
    } finally {
      setAuthState("signed_out");
    }
  }

  if (authState === "loading") {
    return (
      <main className="signin-loading" role="status">
        Checking your AxiomWeave session…
      </main>
    );
  }
  if (authState === "signed_out") {
    return <SignIn onSignedIn={() => setAuthState("signed_in")} />;
  }
  return (
    <Workspace
      onLogout={() => {
        void signOut();
      }}
    />
  );
}
