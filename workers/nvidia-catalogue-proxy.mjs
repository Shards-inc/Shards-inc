// Shards NVIDIA Catalogue: minimal, read-only GitHub static-file proxy.
// Cloudflare Worker deployed as shards-nvidia-catalogue.
// No secrets, paid APIs, analytics, dynamic code evaluation, or external writes.
const SOURCE = "https://raw.githubusercontent.com/Shards-inc/Shards-inc/main/docs/nvidia-catalogue/";
const ALLOWED = Object.freeze({
  "/": ["index.html", "text/html; charset=utf-8"],
  "/index.html": ["index.html", "text/html; charset=utf-8"],
  "/catalogue-data.js": ["catalogue-data.js", "application/javascript; charset=utf-8"],
  "/catalogue.json": ["catalogue.json", "application/json; charset=utf-8"],
  "/changes.json": ["changes.json", "application/json; charset=utf-8"],
  "/watch-state.json": ["watch-state.json", "application/json; charset=utf-8"],
  "/README.md": ["README.md", "text/markdown; charset=utf-8"]
});
export default {
  async fetch(request) {
    if (request.method !== "GET" && request.method !== "HEAD")
      return new Response("Method Not Allowed", {status: 405, headers: {"Allow": "GET, HEAD"}});
    const url = new URL(request.url);
    const item = ALLOWED[url.pathname];
    if (!item) return new Response("Not Found", {status: 404});
    let upstream;
    try {
      upstream = await fetch(SOURCE + item[0], {
        method: "GET",
        headers: {"Accept": "*/*", "User-Agent": "Shards-NVIDIA-Catalogue/1.0"},
        cf: {cacheEverything: true, cacheTtl: item[0] === "catalogue-data.js" ? 60 : 180}
      });
    } catch (error) {
      return new Response("Source temporarily unavailable", {status: 503, headers: {"Retry-After": "60"}});
    }
    if (!upstream.ok) {
      return new Response("Catalogue source not yet available", {
        status: upstream.status === 404 ? 503 : 502,
        headers: {"Retry-After": "60"}
      });
    }
    const headers = new Headers({
      "Content-Type": item[1],
      "Cache-Control": item[0] === "catalogue-data.js" ? "public, max-age=60" : "public, max-age=180",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
      "X-Frame-Options": "DENY",
      "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
      "Content-Security-Policy": "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    });
    return new Response(request.method === "HEAD" ? null : upstream.body, {
      status: 200, headers
    });
  }
};
