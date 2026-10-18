import { useState } from "react";
import {
  createUserWithEmailAndPassword,
  GoogleAuthProvider,
  sendEmailVerification,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut as firebaseSignOut,
} from "firebase/auth";
import { ArrowRight, Check, Eye, EyeOff, Film, FolderClock, LoaderCircle, PackageCheck, ShieldCheck, Sparkles } from "lucide-react";
import { useAuth } from "../auth";
import { firebaseAuth, firebaseConfigured, firebaseMissingKeys } from "../firebase";

function friendlyAuthError(error: unknown): string {
  const code = typeof error === "object" && error && "code" in error ? String((error as { code?: string }).code || "") : "";
  if (code.includes("invalid-credential") || code.includes("wrong-password") || code.includes("user-not-found")) return "The email or password is not correct.";
  if (code.includes("email-already-in-use")) return "An account already exists for this email. Sign in instead.";
  if (code.includes("weak-password")) return "Use a stronger password with at least 6 characters.";
  if (code.includes("popup-closed-by-user")) return "Google sign-in was closed before it finished.";
  if (code.includes("popup-blocked")) return "Your browser blocked the Google sign-in popup. Allow popups for ReviveAI and try again.";
  if (code.includes("too-many-requests")) return "Too many sign-in attempts. Wait a moment and try again.";
  if (code.includes("network-request-failed")) return "Network connection failed while contacting Firebase.";
  return error instanceof Error ? error.message : "Authentication failed. Please try again.";
}

export function SignInPage({ serviceError }: { serviceError?: string | null }) {
  const { establishSession } = useAuth();
  const [mode, setMode] = useState<"signin" | "create">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [pending, setPending] = useState<"EMAIL" | "GOOGLE" | "RESET" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(serviceError || null);

  async function finishFirebaseUser(user: { getIdToken: (forceRefresh?: boolean) => Promise<string> }) {
    const idToken = await user.getIdToken(true);
    await establishSession(idToken);
    if (firebaseAuth) await firebaseSignOut(firebaseAuth);
  }

  async function submitEmail(event: React.FormEvent) {
    event.preventDefault();
    if (!firebaseAuth) return;
    setPending("EMAIL"); setError(null); setMessage(null);
    try {
      if (mode === "create") {
        const credential = await createUserWithEmailAndPassword(firebaseAuth, email.trim(), password);
        await sendEmailVerification(credential.user).catch(() => undefined);
        await finishFirebaseUser(credential.user);
      } else {
        const credential = await signInWithEmailAndPassword(firebaseAuth, email.trim(), password);
        await finishFirebaseUser(credential.user);
      }
    } catch (err) {
      setError(friendlyAuthError(err));
    } finally {
      setPending(null);
    }
  }

  async function continueWithGoogle() {
    if (!firebaseAuth) return;
    setPending("GOOGLE"); setError(null); setMessage(null);
    try {
      const provider = new GoogleAuthProvider();
      provider.setCustomParameters({ prompt: "select_account" });
      const credential = await signInWithPopup(firebaseAuth, provider);
      await finishFirebaseUser(credential.user);
    } catch (err) {
      setError(friendlyAuthError(err));
    } finally {
      setPending(null);
    }
  }

  async function resetPassword() {
    if (!firebaseAuth || !email.trim()) {
      setError("Enter your email address first, then choose Forgot password.");
      return;
    }
    setPending("RESET"); setError(null); setMessage(null);
    try {
      await sendPasswordResetEmail(firebaseAuth, email.trim());
      setMessage("If that email has a ReviveAI account, Firebase will send password reset instructions.");
    } catch (err) {
      setError(friendlyAuthError(err));
    } finally {
      setPending(null);
    }
  }

  const busy = Boolean(pending);

  return (
    <div className="auth-page">
      <header className="auth-brandbar">
        <div className="brand" aria-label="ReviveAI">
          <div className="brand-mark" aria-hidden="true"><Sparkles size={19} strokeWidth={2.2} /></div>
          <div><div className="brand-name">ReviveAI</div><div className="brand-subtitle">Creator Workspace</div></div>
        </div>
        <div className="auth-secure-pill"><ShieldCheck size={14} /> Secure workspace</div>
      </header>

      <main className="auth-layout">
        <section className="auth-value-panel" aria-labelledby="auth-value-title">
          <div className="auth-kicker">Your creative work, ready when you are</div>
          <h1 id="auth-value-title">Create, publish, and learn continuously.</h1>
          <div aria-label="ReviveAI lifecycle: Understand, Plan, Create, Publish, Improve" style={{ width: "100%", maxWidth: 400, margin: "12px auto 14px" }}>
            <svg viewBox="0 0 380 250" role="img" aria-label="Five stages of ReviveAI content creation" style={{ width: "100%", height: "auto" }}>
              <circle cx="190" cy="125" r="91" fill="none" stroke="#343954" strokeWidth="18" />
              <circle cx="190" cy="125" r="91" fill="none" stroke="#806cf1" strokeWidth="8" strokeDasharray="420 572" transform="rotate(-95 190 125)" strokeLinecap="round" />
              {([ [190,34,"1","UNDERSTAND"], [277,95,"2","PLAN"], [248,198,"3","CREATE"], [132,198,"4","PUBLISH"], [103,95,"5","IMPROVE"] ] as const).map(([x,y,n,label]) => <g key={n}>
                <circle cx={x} cy={y} r="34" fill={n === "3" ? "#6551be" : "#25304b"} stroke={n === "3" ? "#b9aaff" : "#67749c"} strokeWidth="1.5" />
                <text x={x} y={y-4} fill="#fff" fontSize="13" fontWeight="800" textAnchor="middle">{n}</text>
                <text x={x} y={y+10} fill="#fff" fontSize="8" textAnchor="middle">{label}</text>
              </g>)}
              <text x="190" y="121" fill="#c4baff" fontWeight="700" fontSize="13" textAnchor="middle">REVIVEAI</text>
              <text x="190" y="137" fill="#aebbd5" fontSize="10" textAnchor="middle">CREATOR LOOP</text>
            </svg>
          </div>
          <p>Resume channels, productions, approvals, and delivery packages exactly where you left them.</p>
          <div className="auth-benefits" style={{ marginTop: 12 }}>
            <article><span><FolderClock size={18} /></span><div><strong>Resume instantly</strong><small>Continue productions from their last saved stage without rebuilding prior work.</small></div></article>
            <article><span><Film size={18} /></span><div><strong>Creator-controlled AI</strong><small>Review and approve briefs, visuals, audio, and publishing copy before they become final.</small></div></article>
            <article><span><PackageCheck size={18} /></span><div><strong>Private workspace</strong><small>Your channels, production assets, approvals, and delivery history stay isolated to your account.</small></div></article>
          </div>
          <div className="auth-trust-line"><Check size={15} /> Secure sign-in · Private workspace · Version history preserved</div>
        </section>

        <section className="auth-card glass-card" aria-label={mode === "signin" ? "Sign in to ReviveAI" : "Create a ReviveAI account"} aria-busy={busy}>
          <div className="auth-card-heading">
            <span className="eyebrow">{mode === "signin" ? "Your workspace" : "New workspace"}</span>
            <h2>{mode === "signin" ? "Sign in to ReviveAI" : "Create your ReviveAI account"}</h2>
            <p>{mode === "signin" ? "Continue your saved creator workspace." : "Start with one channel and grow into a private multi-channel workspace."}</p>
          </div>

          {!firebaseConfigured ? (
            <div className="auth-config-warning" role="alert">
              <strong>Firebase setup required</strong>
              <p>Add the Firebase web configuration to <code>frontend/.env</code>, then restart Vite.</p>
              <small>Missing: {firebaseMissingKeys.join(", ")}</small>
            </div>
          ) : (
            <>
              <button className="google-auth-button" type="button" onClick={continueWithGoogle} disabled={busy}>
                {pending === "GOOGLE" ? <LoaderCircle className="spinner" size={17} aria-hidden="true" /> : <span className="google-letter" aria-hidden="true">G</span>}
                {pending === "GOOGLE" ? "Connecting…" : "Continue with Google"}
              </button>

              <div className="auth-divider"><span>or use email</span></div>

              <form className="auth-form" onSubmit={submitEmail} aria-busy={pending === "EMAIL"}>
                <label>Email address<input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" required /></label>
                <label>Password
                  <div className="auth-password-field">
                    <input type={showPassword ? "text" : "password"} autoComplete={mode === "signin" ? "current-password" : "new-password"} value={password} onChange={(event) => setPassword(event.target.value)} placeholder="At least 6 characters" minLength={6} required />
                    <button type="button" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? "Hide password" : "Show password"}>{showPassword ? <EyeOff size={17} /> : <Eye size={17} />}</button>
                  </div>
                </label>
                {mode === "signin" && <button className="auth-text-button" type="button" onClick={resetPassword} disabled={busy}>{pending === "RESET" ? "Sending reset…" : "Forgot password?"}</button>}
                <button className="primary-button auth-submit" type="submit" disabled={busy}>
                  {pending === "EMAIL" && <LoaderCircle className="spinner" size={16} aria-hidden="true" />}
                  {pending === "EMAIL" ? "Please wait…" : mode === "signin" ? "Sign in" : "Create account"}
                  {pending !== "EMAIL" && <ArrowRight size={16} />}
                </button>
              </form>

              {(error || serviceError) && <div className="auth-feedback error" role="alert" aria-live="assertive">{error || serviceError}</div>}
              {message && <div className="auth-feedback success" role="status" aria-live="polite">{message}</div>}

              <div className="auth-mode-switch">
                <span>{mode === "signin" ? "New to ReviveAI?" : "Already have an account?"}</span>
                <button type="button" onClick={() => { setMode(mode === "signin" ? "create" : "signin"); setError(null); setMessage(null); }}>
                  {mode === "signin" ? "Create an account" : "Sign in"}<ArrowRight size={14} aria-hidden="true" />
                </button>
              </div>
            </>
          )}

          <p className="auth-terms"><ShieldCheck size={13} aria-hidden="true" /> Your production data stays isolated to your signed-in workspace.</p>
        </section>
      </main>
    </div>
  );
}

export function AuthLoadingScreen() {
  return <div className="auth-loading" role="status" aria-live="polite"><div className="brand-mark"><Sparkles size={21} /></div><strong>ReviveAI</strong><span>Securing your workspace…</span></div>;
}
