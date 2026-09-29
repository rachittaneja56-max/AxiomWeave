import { useEffect, useState } from "react";
import { ArrowLeft, Plus } from "lucide-react";
import { api } from "./api";
import { AppShell } from "./components/AppShell";
import { DashboardScreen } from "./screens/DashboardScreen";
import { NewTransformationScreen } from "./screens/NewTransformationScreen";
import { ReviewWorkspace } from "./screens/ReviewWorkspace";
import { SignInScreen } from "./screens/SignInScreen";
import type { OutputType, WorkspaceScreen } from "./types";
import { isRecord } from "./utils";

type AuthState = "loading" | "signed_out" | "signed_in";

function Workspace({ onLogout }: { onLogout: () => Promise<boolean> }) {
  const [screen, setScreen] = useState<WorkspaceScreen>("dashboard");
  const [reviewId, setReviewId] = useState<number | null>(null);
  const [reviewTitle, setReviewTitle] = useState("Review workspace");
  const [reviewSourceVersion, setReviewSourceVersion] = useState(1);
  const [logoutError, setLogoutError] = useState(false);
  const [pendingOutput, setPendingOutput] = useState<OutputType | undefined>();

  function openReview(
    id: number,
    title: string,
    sourceVersion: number,
    outputType?: OutputType,
  ) {
    setReviewId(id);
    setReviewTitle(title || "Untitled transformation");
    setReviewSourceVersion(sourceVersion);
    setPendingOutput(outputType);
    setScreen("review");
  }

  function navigate(destination: "dashboard" | "new") {
    setScreen(destination);
    setLogoutError(false);
  }

  async function handleLogout() {
    setLogoutError(false);
    if (!(await onLogout())) setLogoutError(true);
  }

  const pageTitle =
    screen === "dashboard"
      ? "Transformations"
      : screen === "new"
        ? "New transformation"
        : reviewTitle;
  const eyebrow =
    screen === "dashboard"
      ? "All transformations"
      : screen === "new"
        ? "Create"
        : "Source V" + reviewSourceVersion + " · Review";
  const description =
    screen === "dashboard"
      ? "Create, review and update source-grounded content."
      : screen === "new"
        ? "Start with a source. Choose the artifacts you need."
        : undefined;

  const headerActions =
    screen === "dashboard" ? (
      <button
        type="button"
        className="button-primary"
        onClick={() => navigate("new")}
      >
        <Plus aria-hidden="true" />
        New transformation
      </button>
    ) : (
      <button
        type="button"
        className="button-quiet"
        onClick={() => navigate("dashboard")}
      >
        <ArrowLeft aria-hidden="true" />
        Transformations
      </button>
    );

  return (
    <AppShell
      screen={screen}
      pageTitle={pageTitle}
      eyebrow={eyebrow}
      description={description}
      headerActions={headerActions}
      logoutError={logoutError}
      onNavigate={navigate}
      onLogout={() => void handleLogout()}
    >
      {screen === "dashboard" && (
        <DashboardScreen
          onCreate={() => navigate("new")}
          onOpenReview={openReview}
        />
      )}
      {screen === "new" && (
        <NewTransformationScreen
          onBack={() => navigate("dashboard")}
          onOpenReview={openReview}
        />
      )}
      {screen === "review" && reviewId !== null && (
        <ReviewWorkspace
          key={reviewId}
          transformationId={reviewId}
          initialOutputType={pendingOutput}
          onBack={() => navigate("dashboard")}
          onTitleChange={setReviewTitle}
          onSourceVersionChange={setReviewSourceVersion}
        />
      )}
    </AppShell>
  );
}

export default function App() {
  const [authState, setAuthState] = useState<AuthState>("loading");

  useEffect(() => {
    let mounted = true;
    void api
      .session()
      .then((body) => {
        if (!mounted) return;
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

  async function signOut(): Promise<boolean> {
    try {
      await api.logout();
      setAuthState("signed_out");
      return true;
    } catch {
      return false;
    }
  }

  if (authState === "loading") {
    return (
      <main className="signin-loading" role="status">
        <span className="loading-mark" aria-hidden="true" />
        <span>Opening your AxiomWeave workspace…</span>
      </main>
    );
  }
  if (authState === "signed_out") {
    return <SignInScreen onSignedIn={() => setAuthState("signed_in")} />;
  }
  return <Workspace onLogout={signOut} />;
}
