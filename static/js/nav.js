/* Shared top nav. Renders into #nav mount. Requires api.js. */
(function () {
  "use strict";

  const HR = (window.HR = window.HR || {});

  HR.renderNav = function renderNav() {
    const mount = document.getElementById("nav");
    if (!mount) return;
    const links = [
      { href: "/", label: "Analyze", match: ["/", "/index.html"] },
      { href: "/builder.html", label: "Builder", match: ["/builder.html"] },
      { href: "/linkedin.html", label: "LinkedIn", match: ["/linkedin.html"] },
    ];
    const path = location.pathname;
    mount.innerHTML =
      '<nav class="top">' +
      '<span class="brand">HR-Agent</span>' +
      links
        .map(
          (l) =>
            `<a href="${l.href}"${l.match.includes(path) ? ' class="active"' : ""}>${l.label}</a>`
        )
        .join("") +
      '<span class="spacer"></span>' +
      '<button id="nav-logout" type="button">Log out</button>' +
      "</nav>";
    document.getElementById("nav-logout").addEventListener("click", HR.logout);
  };

  HR.renderNav();
})();
