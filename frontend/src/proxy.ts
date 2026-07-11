import { NextResponse, type NextRequest } from "next/server";

// Dashboard paths guarded by the presence of the "session" cookie. Auth is
// cookie-session only; this proxy just gates navigation, the backend is the
// real authority (401 -> client redirects to /signin).
const GUARDED = [
  "/analyze",
  "/builder",
  "/linkedin",
  "/jobs",
  "/people",
  "/history",
  "/settings",
  "/dashboard",
];

export function proxy(req: NextRequest) {
  const { pathname } = req.nextUrl;

  // /dashboard -> /analyze
  if (pathname === "/dashboard") {
    const url = req.nextUrl.clone();
    url.pathname = "/analyze";
    return NextResponse.redirect(url);
  }

  // /companies (removed) -> /people
  if (pathname === "/companies" || pathname.startsWith("/companies/")) {
    const url = req.nextUrl.clone();
    url.pathname = "/people";
    return NextResponse.redirect(url);
  }

  const guarded = GUARDED.some((p) => pathname === p || pathname.startsWith(p + "/"));
  if (!guarded) return NextResponse.next();

  const hasSession = req.cookies.has("session");
  if (!hasSession) {
    const url = req.nextUrl.clone();
    url.pathname = "/signin";
    url.search = "";
    // Preserve the deep link so signin can bounce back (internal paths only).
    if (pathname.startsWith("/") && !pathname.startsWith("//")) {
      url.searchParams.set("next", pathname + req.nextUrl.search);
    }
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/dashboard",
    "/analyze/:path*",
    "/builder/:path*",
    "/linkedin/:path*",
    "/jobs/:path*",
    "/people/:path*",
    "/companies/:path*",
    "/history/:path*",
    "/settings/:path*",
  ],
};
