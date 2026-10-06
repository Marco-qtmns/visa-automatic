"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { ApiError, api, type AuthUser } from "@/lib/api/client";

const AuthContext = createContext<AuthUser | null>(null);
export function useCurrentUser() { return useContext(AuthContext); }

export function AuthShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [checking, setChecking] = useState(pathname !== "/login");
  const [authError, setAuthError] = useState("");

  useEffect(() => {
    const expired = () => {
      setUser(null);
      router.replace(`/login?returnTo=${encodeURIComponent(pathname)}`);
    };
    window.addEventListener("visa-auth-expired", expired);
    return () => window.removeEventListener("visa-auth-expired", expired);
  }, [pathname, router]);

  useEffect(() => {
    if (pathname === "/login") { setChecking(false); return; }
    let active = true;
    setChecking(true);
    setAuthError("");
    api.me()
      .then((result) => { if (active) setUser(result.user); })
      .catch((error) => {
        if (active && error instanceof ApiError && error.status === 401) {
          router.replace(`/login?returnTo=${encodeURIComponent(pathname)}`);
        } else if (active) {
          setAuthError("The employee session could not be verified.");
        }
      })
      .finally(() => { if (active) setChecking(false); });
    return () => { active = false; };
  }, [pathname, router]);

  async function logout() {
    await api.logout();
    setUser(null);
    router.replace("/login");
  }

  if (checking) return <main className="page-shell"><div className="state-panel">Checking session…</div></main>;
  if (pathname !== "/login" && !user) {
    return <main className="page-shell"><div className="state-panel">{authError || "Redirecting to sign in…"}</div></main>;
  }
  return (
    <AuthContext.Provider value={user}>
      {pathname !== "/login" && user ? (
        <header className="app-header">
          <Link href="/cases" className="brand"><span className="brand-mark">VA</span><span><strong>Visa Automatic</strong><small>Case management</small></span></Link>
          <nav aria-label="Primary navigation">
            <span className="user-identity">{user.display_name} · {user.role}</span>
            <Link href="/cases">Cases</Link>
            <Link href="/cases/new" className="button button-small">New case</Link>
            <button type="button" className="button button-small" onClick={() => void logout()}>Log out</button>
          </nav>
        </header>
      ) : null}
      <main className="page-shell">{children}</main>
    </AuthContext.Provider>
  );
}
