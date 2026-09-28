import { useEffect, useState } from "react";

type HealthState = "loading" | "online" | "offline";

export default function App() {
  const [health, setHealth] = useState<HealthState>("loading");

  useEffect(() => {
    const controller = new AbortController();

    async function checkHealth() {
      try {
        const response = await fetch("/api/health", {
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("Backend returned an error");
        const body: unknown = await response.json();
        if (
          typeof body !== "object" ||
          body === null ||
          !("status" in body) ||
          body.status !== "ok"
        ) {
          throw new Error("Backend returned an invalid health response");
        }
        setHealth("online");
      } catch {
        if (!controller.signal.aborted) setHealth("offline");
      }
    }

    void checkHealth();
    return () => controller.abort();
  }, []);

  const statusText = {
    loading: "Checking backend…",
    online: "Backend connected",
    offline: "Backend unavailable",
  }[health];

  return (
    <main className="page-shell">
      <section className="welcome-card" aria-labelledby="page-title">
        <p className="eyebrow">Smart India Hackathon 2026 · NTRO</p>
        <h1 id="page-title">SIH26154 — Content Transformation MVP</h1>
        <p className="intro">
          A development foundation for transforming source content into clear,
          audience-ready communication artifacts.
        </p>
        <div
          className={`health health--${health}`}
          role="status"
          aria-live="polite"
        >
          <span className="health-dot" aria-hidden="true" />
          {statusText}
        </div>
        <p className="scope-note">
          This development page checks connectivity. Content transformation is
          not implemented yet.
        </p>
      </section>
    </main>
  );
}
