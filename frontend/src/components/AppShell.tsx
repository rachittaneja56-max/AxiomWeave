import { useEffect, useState, type ReactNode } from "react";
import { Files, LogOut, Menu, Plus, X } from "lucide-react";
import type { WorkspaceScreen } from "../types";
import { BrandMark } from "./BrandMark";
import { WeaveAssistant } from "./WeaveAssistant";

type AppShellProps = {
  screen: WorkspaceScreen;
  pageTitle: string;
  description?: string;
  headerActions?: ReactNode;
  logoutError?: boolean;
  username: string;
  onNavigate: (screen: "dashboard" | "new") => void;
  onLogout: () => void;
  children: ReactNode;
  contextualNavigation?: ReactNode;
  projectTitle?: string;
  sourceVersion?: number | null;
  assistantContext: string;
  transformationId: number | null;
  creationPage?: boolean;
  onExitCreationPage?: () => void;
  onTransformationCreated: (
    id: number,
    title: string,
    sourceVersion: number,
  ) => void;
  onWorkspaceChanged: () => void;
};

export function AppShell({
  screen,
  pageTitle,
  description,
  headerActions,
  logoutError = false,
  username,
  onNavigate,
  onLogout,
  children,
  contextualNavigation,
  projectTitle,
  sourceVersion,
  assistantContext,
  transformationId,
  creationPage = false,
  onExitCreationPage = () => {},
  onTransformationCreated,
  onWorkspaceChanged,
}: AppShellProps) {
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (!menuOpen) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setMenuOpen(false);
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [menuOpen]);

  function navigate(destination: "dashboard" | "new") {
    onNavigate(destination);
    setMenuOpen(false);
  }

  return (
    <div
      className={
        "app-frame" + (screen === "review" ? " app-frame--review" : "")
      }
    >
      <button
        type="button"
        className={"sidebar-scrim" + (menuOpen ? " is-visible" : "")}
        aria-label="Close navigation"
        tabIndex={menuOpen ? 0 : -1}
        onClick={() => setMenuOpen(false)}
      />
      <aside
        className={"app-sidebar" + (menuOpen ? " is-open" : "")}
        onClick={(event) => {
          if (
            (event.target as HTMLElement).closest(
              ".review-sidebar-context__item",
            )
          )
            setMenuOpen(false);
        }}
      >
        <div className="sidebar-brand">
          <BrandMark />
        </div>
        <nav className="sidebar-nav" aria-label="Main navigation">
          <button
            type="button"
            className={"sidebar-link" + (screen !== "new" ? " is-active" : "")}
            aria-current={screen !== "new" ? "page" : undefined}
            onClick={() => navigate("dashboard")}
          >
            <Files aria-hidden="true" />
            <span>Transformations</span>
          </button>
          <button
            type="button"
            className={"sidebar-link" + (screen === "new" ? " is-active" : "")}
            aria-current={screen === "new" ? "page" : undefined}
            onClick={() => navigate("new")}
          >
            <Plus aria-hidden="true" />
            <span>New transformation</span>
          </button>
        </nav>
        {screen === "review" && projectTitle && (
          <div className="sidebar-project" aria-label="Current project">
            <p className="sidebar-section-label">Current project</p>
            <strong title={projectTitle}>{projectTitle}</strong>
            {sourceVersion !== null && sourceVersion !== undefined && (
              <span>Source V{sourceVersion}</span>
            )}
          </div>
        )}
        {contextualNavigation}
        <div id="review-context-navigation" />
        <div className="sidebar-footer">
          <div className="sidebar-footer__line" />
          <div className="sidebar-account" aria-label="Signed-in account">
            <span>{username}</span>
          </div>
          <button type="button" className="sidebar-link" onClick={onLogout}>
            <LogOut aria-hidden="true" />
            <span>Sign out</span>
          </button>
        </div>
      </aside>
      <div className="app-main">
        <header className="app-topbar">
          <button
            type="button"
            className="mobile-menu-toggle"
            aria-label={
              menuOpen ? "Close navigation menu" : "Open navigation menu"
            }
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen(!menuOpen)}
          >
            {menuOpen ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
          </button>
          <div className="topbar-spacer" aria-hidden="true" />
          <div
            className={
              "topbar-actions" +
              (screen === "review" ? " topbar-actions--review" : "")
            }
          >
            {headerActions}
          </div>
        </header>
        <main className={"content-area content-area--" + screen}>
          <div className="page-heading">
            <div>
              <h1>{pageTitle}</h1>
              {description && <p>{description}</p>}
            </div>
          </div>
          {logoutError && (
            <p className="notice notice--error" role="alert">
              Sign out could not be completed. Please try again.
            </p>
          )}
          {children}
        </main>
        <WeaveAssistant
          transformationId={transformationId}
          contextLabel={assistantContext}
          creationMode={creationPage}
          creationPage={creationPage}
          onExitCreationPage={onExitCreationPage}
          onNavigateNew={() => navigate("new")}
          onTransformationCreated={onTransformationCreated}
          onWorkspaceChanged={onWorkspaceChanged}
        />
      </div>
    </div>
  );
}
