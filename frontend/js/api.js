// Comunicacion con el servidor. Con ?mock=ok o ?mock=errors se usan los JSON de frontend/mock/
// en lugar de la API, para trabajar en la vista sin el backend.

const MOCKS = { ok: "mock/response_ok.json", errors: "mock/response_errors.json" };

export function mockMode() {
  const value = new URLSearchParams(window.location.search).get("mock");
  return value in MOCKS ? value : null;
}

async function readJson(response) {
  let data = null;
  try {
    data = await response.json();
  } catch {
    // la respuesta no era JSON
  }
  if (!response.ok) {
    throw new Error(data?.error ?? `El servidor respondió ${response.status}.`);
  }
  return data;
}

export async function compileSource(source, registerCount) {
  const mock = mockMode();
  if (mock) {
    return readJson(await fetch(MOCKS[mock]));
  }
  const response = await fetch("/api/compile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source, register_count: registerCount }),
  });
  return readJson(response);
}

export async function fetchExamples() {
  const data = await readJson(await fetch("/api/examples"));
  return Array.isArray(data?.examples) ? data.examples : [];
}
