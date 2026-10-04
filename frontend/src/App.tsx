import { useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { api } from "./api";
import { AppShell } from "./components/AppShell";
import { DashboardScreen } from "./screens/DashboardScreen";
import { NewTransformationScreen } from "./screens/NewTransformationScreen";
import { ReviewWorkspace } from "./screens/ReviewWorkspace";
import { SignInScreen } from "./screens/SignInScreen";
import type { OutputType, WorkspaceScreen } from "./types";
import { isRecord } from "./utils";

type AuthState = "loading" | "signed_out" | "signed_in";

function Workspace({
  onLogout,
  username,
}: {
  onLogout: () => Promise<boolean>;
  username: string;
}) {
  const [screen, setScreen] = useState<WorkspaceScreen>("dashboard");
  const [reviewId, setReviewId] = useState<number | null>(null);
  const [reviewTitle, setReviewTitle] = useState("Review workspace");
  const [reviewSourceVersion, setReviewSourceVersion] = useState(1);
  const [assistantContext, setAssistantContext] = useState("Project overview");
  const [reviewRefresh, setReviewRefresh] = useState(0);
  const [logoutError, setLogoutError] = useState(false);
  const [pendingOutput, setPendingOutput] = useState<OutputType | undefined>();
  const [creationPath, setCreationPath] = useState<
    "choose" | "weave" | "manual"
  >("choose");

  function openReview(
    id: number,
    title: string,
    sourceVersion: number,
    outputType?: OutputType,
  ) {
    setReviewId(id);
    setReviewTitle(title || "Untitled transformation");
    setReviewSourceVersion(sourceVersion);
    setAssistantContext("Project overview");
    setPendingOutput(outputType);
    setScreen("review");
  }

  function navigate(destination: "dashboard" | "new") {
    setScreen(destination);
    if (destination === "new") setCreationPath("choose");
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
  const description =
    screen === "dashboard"
      ? "Create, review and update source-grounded content."
      : screen === "new"
        ? "Describe your source and the materials you want to create."
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
    ) : null;

  return (
    <AppShell
      screen={screen}
      pageTitle={pageTitle}
      description={description}
      headerActions={headerActions}
      logoutError={logoutError}
      username={username}
      projectTitle={screen === "review" ? reviewTitle : undefined}
      sourceVersion={screen === "review" ? reviewSourceVersion : null}
      assistantContext={
        screen === "dashboard"
          ? "Dashboard"
          : screen === "new"
            ? "Creating a transformation"
            : assistantContext
      }
      transformationId={screen === "review" ? reviewId : null}
      creationPage={screen === "new" && creationPath === "weave"}
      onExitCreationPage={() => setCreationPath("choose")}
      onNavigate={navigate}
      onLogout={() => void handleLogout()}
      onTransformationCreated={(id, title, sourceVersion) =>
        openReview(id, title, sourceVersion)
      }
      onWorkspaceChanged={() => setReviewRefresh((value) => value + 1)}
    >
      {screen === "dashboard" && (
        <DashboardScreen
          onCreate={() => navigate("new")}
          onOpenReview={openReview}
        />
      )}
      {screen === "new" && (
        <NewTransformationScreen
          path={creationPath}
          onChooseWeave={() => setCreationPath("weave")}
          onChooseManual={() => setCreationPath("manual")}
          onBackToOptions={() => setCreationPath("choose")}
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
          onAssistantContextChange={setAssistantContext}
          projectTitle={reviewTitle}
          refreshKey={reviewRefresh}
        />
      )}
    </AppShell>
  );
}

export default function App() {
  const [authState, setAuthState] = useState<AuthState>("loading");
  const [username, setUsername] = useState("");

  useEffect(() => {
    let mounted = true;
    void api
      .session()
      .then((body) => {
        if (!mounted) return;
        if (isRecord(body) && typeof body.username === "string")
          setUsername(body.username);
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
    return (
      <SignInScreen
        onSignedIn={() => {
          void api.session().then((body) => {
            if (isRecord(body) && typeof body.username === "string")
              setUsername(body.username);
          });
          setAuthState("signed_in");
        }}
      />
    );
  }
  return <Workspace onLogout={signOut} username={username} />;
}
