import { useEffect, useState, type ReactNode } from "react";
import { ArrowUpRight, Files, LogOut, Menu, Plus, X } from "lucide-react";
import type { WorkspaceScreen } from "../types";
import { BrandMark } from "./BrandMark";

type AppShellProps = {
  screen: WorkspaceScreen;
  pageTitle: string;
  eyebrow?: string;
  description?: string;
  headerActions?: ReactNode;
  logoutError?: boolean;
  onNavigate: (screen: "dashboard" | "new") => void;
  onLogout: () => void;
  children: ReactNode;
};

export function AppShell({
  screen,
  pageTitle,
  eyebrow = "Workspace",
  description,
  headerActions,
  logoutError = false,
  onNavigate,
  onLogout,
  children,
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
    <div className="app-frame">
      <button
        type="button"
        className={"sidebar-scrim" + (menuOpen ? " is-visible" : "")}
        aria-label="Close navigation"
        tabIndex={menuOpen ? 0 : -1}
        onClick={() => setMenuOpen(false)}
      />
      <aside className={"app-sidebar" + (menuOpen ? " is-open" : "")}>
        <div className="sidebar-brand">
          <BrandMark />
          <span className="sidebar-caption">Source-grounded workspace</span>
        </div>
        <nav className="sidebar-nav" aria-label="Main navigation">
          <p className="sidebar-section-label">Workspace</p>
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
        <div className="sidebar-footer">
          <div className="sidebar-footer__line" />
          <p className="sidebar-footer__promise">
            <span className="promise-dot" aria-hidden="true" />
            One source. Many artifacts.
          </p>
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
          <div className="breadcrumb" aria-label="Breadcrumb">
            <span>Workspace</span>
            <ArrowUpRight aria-hidden="true" />
            <span>{eyebrow}</span>
          </div>
          <div className="topbar-actions">{headerActions}</div>
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
      </div>
    </div>
  );
}
