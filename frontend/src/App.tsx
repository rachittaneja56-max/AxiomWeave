import { useEffect, useState, type FormEvent } from "react";

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

export default function App() {
  const [health, setHealth] = useState<HealthState>("loading");
  const [request, setRequest] =
    useState<TransformationRequest>(INITIAL_REQUEST);
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
          <p className="eyebrow">Smart India Hackathon 2026 · NTRO</p>
          <h1>Content transformation</h1>
          <p className="intro">
            Prepare one source and choose the communication materials you need.
          </p>
        </div>
        <div className={`health health--${health}`} aria-live="polite">
          <span className="health-dot" aria-hidden="true" />
          {healthText}
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
              <p>Paste the text you want to adapt.</p>
            </div>
          </div>
          <label htmlFor="source-text">Text source</label>
          <textarea
            id="source-text"
            rows={8}
            value={request.source_text}
            onChange={(event) =>
              updateRequest("source_text", event.target.value)
            }
            placeholder="Paste or write your source text here"
          />
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
          <button type="submit" disabled={isSubmitting}>
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
