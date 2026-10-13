export type FieldError = { field: string; message: string; row?: number };

export class ApiError extends Error {
  status: number;
  detail: string;
  errors: FieldError[];
  constructor(status: number, detail: string, errors: FieldError[] = []) {
    super(detail);
    this.status = status;
    this.detail = detail;
    this.errors = errors;
  }
}

let csrfToken: string | null = null;
export function setCsrf(token: string | null | undefined) {
  csrfToken = token ?? null;
}

const BASE = '/api/v1';

async function request<T>(method: string, path: string, body?: unknown, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {};
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
  if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json';
  if (method !== 'GET' && csrfToken) headers['X-CSRF-Token'] = csrfToken;
  const res = await fetch(BASE + path, {
    method,
    headers,
    credentials: 'same-origin',
    body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
    ...init,
  });
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get('content-type') || '';
  if (!res.ok) {
    let detail = res.statusText || 'Request failed.';
    let errors: FieldError[] = [];
    if (ct.includes('application/json')) {
      const data = await res.json();
      detail = data.detail ?? detail;
      errors = data.errors ?? [];
    }
    throw new ApiError(res.status, detail, errors);
  }
  if (ct.includes('application/json')) return (await res.json()) as T;
  return (await res.blob()) as unknown as T;
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body ?? {}),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body ?? {}),
  delete: <T>(path: string) => request<T>('DELETE', path),
  upload: <T>(path: string, form: FormData) => request<T>('POST', path, form),
};

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.detail;
  if (e instanceof Error) return e.message;
  return 'Something went wrong. Try again.';
}

export function fieldErrors(e: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  if (e instanceof ApiError) for (const er of e.errors) if (er.field) out[er.field] = er.message;
  return out;
}
