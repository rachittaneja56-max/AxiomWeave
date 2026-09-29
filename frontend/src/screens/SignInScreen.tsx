import { useEffect, useState, type FormEvent } from "react";
import { ArrowRight, KeyRound, UserRound } from "lucide-react";
import { api, ApiError } from "../api";
import { BrandMark } from "../components/BrandMark";
import { isRecord } from "../utils";

export function SignInScreen({ onSignedIn }: { onSignedIn: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [registrationEnabled, setRegistrationEnabled] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    let active = true;
    void api
      .authConfig()
      .then((body) => {
        if (active && isRecord(body)) {
          setRegistrationEnabled(body.registration_enabled === true);
        }
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setMessage(null);
    try {
      const body = await api.login(username, password, registering);
      if (isRecord(body) && body.authenticated === true) {
        setPassword("");
        onSignedIn();
        return;
      }
      setMessage("Sign-in could not be completed. Please try again.");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setMessage(
          registering
            ? "Account creation could not be completed."
            : "Invalid username or password.",
        );
      } else if (error instanceof ApiError && error.status === 429) {
        setMessage("Too many sign-in attempts. Please try again later.");
      } else if (error instanceof ApiError && error.status === 409) {
        setMessage("That username is unavailable.");
      } else if (error instanceof ApiError && error.status === 403) {
        setMessage("Account creation is currently closed.");
      } else {
        setMessage(
          "Could not reach AxiomWeave. Check the connection and try again.",
        );
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="signin-page">
      <section className="signin-intro" aria-labelledby="product-name">
        <BrandMark />
        <div className="signin-intro__main">
          <p className="eyebrow">Source-grounded content workspace</p>
          <h1 id="product-name">
            One source.
            <br />
            Many artifacts.
          </h1>
          <p className="signin-tagline">
            Every claim connected to the material it came from.
          </p>
          <div className="signin-weave" aria-hidden="true">
            <div className="signin-weave__source">Source</div>
            <svg viewBox="0 0 430 132" preserveAspectRatio="none">
              <path d="M5 64 C95 64,105 14,188 14 S285 118,425 118" />
              <path d="M5 64 C115 64,108 64,205 64 S312 64,425 64" />
              <path d="M5 64 C95 64,105 114,188 114 S285 10,425 10" />
              <circle cx="5" cy="64" r="5" />
              <circle cx="425" cy="10" r="5" />
              <circle cx="425" cy="64" r="5" />
              <circle cx="425" cy="118" r="5" />
            </svg>
            <div className="signin-weave__outputs">
              <span>Summary</span>
              <span>Post</span>
              <span>Advisory</span>
            </div>
          </div>
          <p className="signin-description">
            Shape clear, useful communication from trusted source material.
            Review each draft and follow its supporting evidence.
          </p>
        </div>
        <p className="signin-footer">Built for careful communication.</p>
      </section>
      <section className="signin-panel" aria-labelledby="signin-heading">
        <div className="signin-card">
          <div className="signin-card__heading">
            <span className="signin-card__icon" aria-hidden="true">
              <KeyRound />
            </span>
            <p className="eyebrow">Your workspace</p>
            <h2 id="signin-heading">
              {registering ? "Create an account" : "Welcome back"}
            </h2>
            <p>
              {registering
                ? "Create your account to save and review transformations."
                : "Sign in to continue to your source-grounded workspace."}
            </p>
          </div>
          <form
            className="signin-form"
            onSubmit={(event) => void submit(event)}
          >
            <label htmlFor="auth-username">Username</label>
            <div className="input-with-icon">
              <UserRound aria-hidden="true" />
              <input
                id="auth-username"
                type="text"
                autoComplete="username"
                spellCheck={false}
                autoCapitalize="none"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                required
              />
            </div>
            <label htmlFor="auth-password">Password</label>
            <input
              id="auth-password"
              type="password"
              autoComplete={registering ? "new-password" : "current-password"}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              minLength={registering ? 15 : undefined}
            />
            {registering && (
              <p className="signin-hint">
                Use at least 15 characters. Passphrases and spaces are allowed.
              </p>
            )}
            <button
              className="button-primary signin-submit"
              type="submit"
              disabled={isSubmitting}
            >
              {isSubmitting
                ? "Please wait…"
                : registering
                  ? "Create account"
                  : "Sign in"}
              {!isSubmitting && <ArrowRight aria-hidden="true" />}
            </button>
          </form>
          {registrationEnabled && (
            <button
              type="button"
              className="text-button signin-toggle"
              onClick={() => {
                setRegistering(!registering);
                setMessage(null);
              }}
            >
              {registering
                ? "Already have an account? Sign in"
                : "Need an account? Create one"}
            </button>
          )}
          {message && (
            <p className="notice notice--error" role="alert">
              {message}
            </p>
          )}
        </div>
        <p className="signin-panel__footnote">
          A considered approach to content, from first source to final review.
        </p>
      </section>
    </main>
  );
}
