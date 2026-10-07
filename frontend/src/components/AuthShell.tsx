"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { ApiError, api, type AuthUser, type ApplicationBootstrap } from "@/lib/api/client";

const AuthContext = createContext<ApplicationBootstrap | null>(null);
export function useCurrentUser() { return useContext(AuthContext)?.user ?? null; }
export function useBootstrapCases() { return useContext(AuthContext)?.case_summary ?? null; }

export function AuthShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [bootstrap, setBootstrap] = useState<ApplicationBootstrap | null>(null);
  const [checking, setChecking] = useState(pathname !== "/login");
  const [authError, setAuthError] = useState("");
  const initialPath = useRef(pathname);

  useEffect(() => {
    const expired = () => {
      setBootstrap(null);
      router.replace(`/login?returnTo=${encodeURIComponent(pathname)}`);
    };
    window.addEventListener("visa-auth-expired", expired);
    return () => window.removeEventListener("visa-auth-expired", expired);
  }, [pathname, router]);

  useEffect(() => {
    const refresh = () => {
      api.bootstrap().then(setBootstrap).catch(() => undefined);
    };
    window.addEventListener("visa-bootstrap-refresh", refresh);
    return () => window.removeEventListener("visa-bootstrap-refresh", refresh);
  }, []);

  useEffect(() => {
    if (initialPath.current === "/login") { setChecking(false); return; }
    let active = true;
    setChecking(true);
    setAuthError("");
    const started = performance.now();
    api.bootstrap()
      .then((result) => {
        if (active) {
          setBootstrap(result);
          performance.measure("visa-app-bootstrap", { start: started, end: performance.now() });
        }
      })
      .catch((error) => {
        if (active && error instanceof ApiError && error.status === 401) {
          router.replace(`/login?returnTo=${encodeURIComponent(initialPath.current)}`);
        } else if (active) {
          setAuthError("The employee session could not be verified.");
        }
      })
      .finally(() => { if (active) setChecking(false); });
    return () => { active = false; };
  }, [router]);

  async function logout() {
    await api.logout();
    setBootstrap(null);
    router.replace("/login");
  }

  if (checking) return <main className="page-shell"><div className="state-panel">Checking session…</div></main>;
  if (pathname !== "/login" && !bootstrap) {
    return <main className="page-shell"><div className="state-panel">{authError || "Redirecting to sign in…"}</div></main>;
  }
  return (
    <AuthContext.Provider value={bootstrap}>
      {pathname !== "/login" && bootstrap ? (
        <header className="app-header">
          <Link href="/cases" className="brand"><span className="brand-mark">VA</span><span><strong>Visa Automatic</strong><small>Case management</small></span></Link>
          <nav aria-label="Primary navigation">
            <span className="user-identity">{bootstrap.user.display_name} · {bootstrap.user.role}</span>
            <Link href="/cases">Cases</Link>
            {bootstrap.user.role === "ADMIN" ? <Link href="/admin/users">Users &amp; audit</Link> : null}
            <Link href="/cases/new" className="button button-small">New application</Link>
            <button type="button" className="button button-small" onClick={() => void logout()}>Log out</button>
          </nav>
        </header>
      ) : null}
      <main className="page-shell">{children}</main>
    </AuthContext.Provider>
  );
}
