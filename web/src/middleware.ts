import { NextResponse, type NextRequest } from "next/server";

// Dashboard paths guarded by the presence of the "session" cookie. Auth is
// cookie-session only; middleware just gates navigation, the backend is the
// real authority (401 -> client redirects to /signin).
const GUARDED = [
  "/analyze",
  "/builder",
  "/linkedin",
  "/jobs",
  "/companies",
  "/history",
  "/settings",
  "/dashboard",
];

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  // /dashboard -> /analyze
  if (pathname === "/dashboard") {
    const url = req.nextUrl.clone();
    url.pathname = "/analyze";
    return NextResponse.redirect(url);
  }

  const guarded = GUARDED.some((p) => pathname === p || pathname.startsWith(p + "/"));
  if (!guarded) return NextResponse.next();

  const hasSession = req.cookies.has("session");
  if (!hasSession) {
    const url = req.nextUrl.clone();
    url.pathname = "/signin";
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
    "/companies/:path*",
    "/history/:path*",
    "/settings/:path*",
  ],
};
