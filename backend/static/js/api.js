/* Shared API helpers. Exposed on window.HR. */
(function () {
  "use strict";

  const HR = (window.HR = window.HR || {});

  HR.esc = function esc(s) {
    return String(s ?? "").replace(/[&<>"]/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]
    ));
  };

  // fetch wrapper: parses JSON, throws Error on {error}/{detail}, redirects on 401.
  HR.api = async function api(url, opts) {
    const res = await fetch(url, opts);
    if (res.status === 401) {
      location = "/login.html";
      throw new Error("unauthorized");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) {
      throw new Error(data.detail || data.error || "Request failed");
    }
    return data;
  };

  // Raw variant for endpoints where the caller wants the Response (e.g. FormData posts).
  HR.authFetch = async function authFetch(url, opts) {
    const res = await fetch(url, opts);
    if (res.status === 401) {
      location = "/login.html";
      throw new Error("unauthorized");
    }
    return res;
  };

  HR.logout = async function logout() {
    await fetch("/api/logout", { method: "POST" });
    location = "/login.html";
  };
})();
