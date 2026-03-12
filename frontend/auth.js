// ── Configuration ────────────────────────────────────────────────────────────
const API_BASE = "https://megatron14-candidate-recruitment-backend.hf.space";

// ── DOM refs ────────────────────────────────────────────────────────────────
const form = document.getElementById("auth-form");
const emailInput = document.getElementById("email");
const passwordInput = document.getElementById("password");
const authBtn = document.getElementById("auth-btn");
const authBtnText = document.getElementById("auth-btn-text");
const authError = document.getElementById("auth-error");
const authSubtitle = document.getElementById("auth-subtitle");
const toggleText = document.getElementById("toggle-text");
const toggleLink = document.getElementById("toggle-link");

// ── State ───────────────────────────────────────────────────────────────────
let isSignUp = false;

// If already logged in, skip to main page
if (sessionStorage.getItem("auth_token")) {
    window.location.replace("index.html");
}

// ── Toggle sign-in / sign-up ────────────────────────────────────────────────
toggleLink.addEventListener("click", (e) => {
    e.preventDefault();
    isSignUp = !isSignUp;
    if (isSignUp) {
        authSubtitle.textContent = "Create a new account";
        authBtnText.textContent = "Sign Up";
        toggleText.textContent = "Already have an account?";
        toggleLink.textContent = "Sign In";
        passwordInput.setAttribute("autocomplete", "new-password");
    } else {
        authSubtitle.textContent = "Sign in to your account";
        authBtnText.textContent = "Sign In";
        toggleText.textContent = "Don't have an account?";
        toggleLink.textContent = "Sign Up";
        passwordInput.setAttribute("autocomplete", "current-password");
    }
    authError.hidden = true;
});

// ── Form submit ─────────────────────────────────────────────────────────────
form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = emailInput.value.trim();
    const password = passwordInput.value;

    if (!email || !password) return;

    setLoading(true);
    authError.hidden = true;

    const endpoint = isSignUp ? "/signup" : "/login";

    try {
        const res = await fetch(new URL(endpoint, API_BASE).toString(), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password }),
        });

        const data = await res.json().catch(() => ({}));

        if (!res.ok) {
            throw new Error(data.detail || `Request failed (${res.status})`);
        }

        // Store token, user id and redirect
        sessionStorage.setItem("auth_token", data.token || "authenticated");
        sessionStorage.setItem("auth_email", data.email || email);
        if (data.user_id) sessionStorage.setItem("auth_user_id", data.user_id);
        window.location.replace("index.html");
    } catch (err) {
        authError.textContent = err.message;
        authError.hidden = false;
    } finally {
        setLoading(false);
    }
});

// ── Helpers ─────────────────────────────────────────────────────────────────
function setLoading(loading) {
    const loader = authBtn.querySelector(".btn-loader");
    if (loading) {
        authBtnText.hidden = true;
        loader.hidden = false;
        authBtn.disabled = true;
    } else {
        authBtnText.hidden = false;
        loader.hidden = true;
        authBtn.disabled = false;
    }
}
