// Cognito Hosted UI + Authorization Code(PKCE) 로그인. 토큰은 이 브라우저에만 저장됩니다.
(function () {
  const C = window.APP_CONFIG || {};
  const KEY = "invest-desk-auth";
  const redirectUri = location.origin + "/";

  function b64url(bytes) {
    return btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  async function sha256(text) {
    return crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  }
  function store(v) { try { v ? localStorage.setItem(KEY, JSON.stringify(v)) : localStorage.removeItem(KEY); } catch (e) {} }
  function load() { try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { return null; } }

  async function tokenRequest(params) {
    const res = await fetch(C.cognitoDomain + "/oauth2/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ client_id: C.clientId, ...params }),
    });
    if (!res.ok) throw new Error("로그인 토큰 발급 실패");
    const t = await res.json();
    const prev = load() || {};
    const saved = { id: t.id_token, refresh: t.refresh_token || prev.refresh, exp: Date.now() + (t.expires_in - 60) * 1000 };
    store(saved);
    return saved;
  }

  async function login() {
    const verifier = b64url(crypto.getRandomValues(new Uint8Array(48)));
    sessionStorage.setItem("pkce", verifier);
    const challenge = b64url(await sha256(verifier));
    const q = new URLSearchParams({
      response_type: "code", client_id: C.clientId, redirect_uri: redirectUri,
      scope: "openid email", code_challenge_method: "S256", code_challenge: challenge,
    });
    location.href = C.cognitoDomain + "/oauth2/authorize?" + q;
  }

  async function handleCallback() {
    const code = new URLSearchParams(location.search).get("code");
    if (!code) return false;
    await tokenRequest({ grant_type: "authorization_code", code, redirect_uri: redirectUri, code_verifier: sessionStorage.getItem("pkce") || "" });
    history.replaceState(null, "", "/" + location.hash);
    return true;
  }

  async function token() {
    let t = load();
    if (!t) return null;
    if (Date.now() > t.exp) {
      if (!t.refresh) { store(null); return null; }
      try { t = await tokenRequest({ grant_type: "refresh_token", refresh_token: t.refresh }); }
      catch (e) { store(null); return null; }
    }
    return t.id;
  }

  function logout() {
    store(null);
    location.href = C.cognitoDomain + "/logout?" + new URLSearchParams({ client_id: C.clientId, logout_uri: redirectUri });
  }

  window.Auth = { login, logout, token, handleCallback };
})();
