/**
 * Pantalla de acceso. Sólo habla con el backend a través de api.ts (R-2).
 *
 * 401 aquí significa credenciales inválidas, no sesión expirada; 429 significa
 * espera. Cada fallo se muestra, nunca se ignora (R-7.1).
 */
import { auth, ApiError } from "./api.js";

const form = document.getElementById("login-form") as HTMLFormElement;
const email = document.getElementById("email") as HTMLInputElement;
const password = document.getElementById("password") as HTMLInputElement;
const feedback = document.getElementById("feedback") as HTMLDivElement;
const submit = document.getElementById("submit") as HTMLButtonElement;

/** Sólo rutas internas: un `next` externo sería una redirección abierta. */
function nextPath(): string {
  const next = new URLSearchParams(location.search).get("next") ?? "/";
  return next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

function showError(message: string): void {
  feedback.textContent = message;
  feedback.hidden = false;
}

// Con sesión ya iniciada la pantalla de acceso no tiene nada que hacer.
auth.me().then(() => location.replace(nextPath()), () => { /* sin sesión: quedarse */ });

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  feedback.hidden = true;

  if (!email.value.trim() || !password.value) {
    showError("Ingresa tu correo y tu contraseña.");
    return;
  }

  submit.disabled = true;
  submit.textContent = "Ingresando…";
  try {
    await auth.login(email.value.trim(), password.value);
    location.replace(nextPath());
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      showError("Correo o contraseña incorrectos.");
    } else if (err instanceof ApiError && err.status === 429) {
      showError("Demasiados intentos fallidos. Espera unos minutos y vuelve a intentar.");
    } else if (err instanceof ApiError && err.status === 0) {
      showError("Sin conexión con el servidor. Revisa tu red e intenta de nuevo.");
    } else {
      showError(err instanceof ApiError ? err.message : "Error inesperado al iniciar sesión.");
    }
    submit.disabled = false;
    submit.textContent = "Ingresar";
  }
});
