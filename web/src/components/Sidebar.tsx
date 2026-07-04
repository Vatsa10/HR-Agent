"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { cn } from "@/lib/format";
import { Spinner } from "@/components/ui";
import { Logo } from "@/components/Logo";

interface NavItem {
  href: string;
  label: string;
  icon: React.ReactNode;
}

// Simple stroke icons (currentColor, 18px) — no external icon dep.
const I = (d: string) => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d={d} />
  </svg>
);

const NAV: NavItem[] = [
  { href: "/analyze", label: "Analyze", icon: I("M4 19V5m0 14h16M8 15l3-4 3 2 4-6") },
  { href: "/builder", label: "Builder", icon: I("M5 3h9l5 5v13H5zM14 3v5h5M8 13h8M8 17h5") },
  { href: "/linkedin", label: "LinkedIn", icon: I("M6 9v9M6 6.5v.01M11 18v-5a2 2 0 0 1 4 0v5M11 18h4M4 4h16v16H4z") },
  { href: "/jobs", label: "Jobs", icon: I("M4 8h16v11H4zM9 8V6a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2") },
  { href: "/companies", label: "Companies", icon: I("M4 20V6a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1v14M14 20V10h5a1 1 0 0 1 1 1v9M3 20h18M7 9h1M7 13h1M10 9h1M10 13h1") },
  { href: "/history", label: "History", icon: I("M3 12a9 9 0 1 0 3-6.7M3 4v4h4M12 8v4l3 2") },
];

function useLogout() {
  const router = useRouter();
  const [loading, setLoading] = React.useState(false);
  const logout = React.useCallback(async () => {
    setLoading(true);
    try {
      await api("/logout", { method: "POST" });
    } catch {
      // ignore — clear client state regardless
    }
    router.push("/signin");
  }, [router]);
  return { logout, loading };
}

function isActive(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(href + "/");
}

function Brand() {
  return (
    <Link href="/analyze" className="flex items-center gap-2 font-semibold tracking-tight text-ink">
      <Logo size={28} />
      <span className="text-[15px]">Do Apply</span>
    </Link>
  );
}

function NavLink({ item, pathname, onClick }: { item: NavItem; pathname: string; onClick?: () => void }) {
  const active = isActive(pathname, item.href);
  return (
    <Link
      href={item.href}
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium",
        "transition-colors duration-150 [transition-timing-function:var(--ease)]",
        active ? "bg-blue-soft text-blue" : "text-ink-soft hover:bg-surface-2 hover:text-ink",
      )}
    >
      <span className={cn("shrink-0", active ? "text-blue" : "text-ink-faint")}>{item.icon}</span>
      {item.label}
    </Link>
  );
}

export function Sidebar() {
  const pathname = usePathname() || "";
  const { logout, loading } = useLogout();
  const [open, setOpen] = React.useState(false);

  // Close the mobile sheet on any route change (covers brand link, back/forward).
  React.useEffect(() => {
    setOpen(false);
  }, [pathname]);

  const settingsActive = isActive(pathname, "/settings");

  const bottom = (onClick?: () => void) => (
    <div className="flex flex-col gap-1 border-t border-line pt-3">
      <Link
        href="/settings"
        onClick={onClick}
        aria-current={settingsActive ? "page" : undefined}
        className={cn(
          "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors duration-150 [transition-timing-function:var(--ease)]",
          settingsActive ? "bg-blue-soft text-blue" : "text-ink-soft hover:bg-surface-2 hover:text-ink",
        )}
      >
        <span className={cn("shrink-0", settingsActive ? "text-blue" : "text-ink-faint")}>
          {I("M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9c.14.6.63 1.06 1.24 1.13")}
        </span>
        Settings
      </Link>
      <button
        onClick={() => {
          onClick?.();
          logout();
        }}
        disabled={loading}
        className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-ink-soft hover:bg-surface-2 hover:text-ink transition-colors duration-150 [transition-timing-function:var(--ease)] disabled:opacity-50"
      >
        <span className="shrink-0 text-ink-faint">
          {loading ? <Spinner size={18} /> : I("M15 12H3m0 0 4-4m-4 4 4 4M14 4h5a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-5")}
        </span>
        Log out
      </button>
    </div>
  );

  return (
    <>
      {/* Desktop: fixed left rail */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-line bg-paper px-3 py-5 md:flex">
        <div className="px-2">
          <Brand />
        </div>
        <nav className="mt-8 flex flex-1 flex-col gap-1">
          {NAV.map((item) => (
            <NavLink key={item.href} item={item} pathname={pathname} />
          ))}
        </nav>
        {bottom()}
      </aside>

      {/* Mobile: top bar + slide-down sheet */}
      <div className="sticky top-0 z-40 flex items-center justify-between border-b border-line bg-paper px-4 py-3 md:hidden">
        <Brand />
        <button
          onClick={() => setOpen((v) => !v)}
          aria-label="Toggle navigation"
          aria-expanded={open}
          className="grid size-9 place-items-center rounded-lg border border-line text-ink-soft hover:bg-surface-2 active:scale-[0.97] transition"
        >
          {open ? I("M6 6l12 12M18 6L6 18") : I("M4 7h16M4 12h16M4 17h16")}
        </button>
      </div>
      {open && (
        <div className="fixed inset-0 top-[57px] z-40 md:hidden">
          <button className="absolute inset-0 bg-ink/10" aria-hidden onClick={() => setOpen(false)} />
          <div className="relative flex max-h-[calc(100vh-57px)] flex-col gap-1 overflow-y-auto border-b border-line bg-paper px-3 py-4">
            <nav className="flex flex-col gap-1">
              {NAV.map((item) => (
                <NavLink key={item.href} item={item} pathname={pathname} onClick={() => setOpen(false)} />
              ))}
            </nav>
            <div className="mt-2">{bottom(() => setOpen(false))}</div>
          </div>
        </div>
      )}
    </>
  );
}

export default Sidebar;
