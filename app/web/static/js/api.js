// HTTP helpers. Errors come back as {detail, errors} (WorkspaceError) or as FastAPI's {detail: [{loc, msg}]}.

export class ApiError extends Error {
  constructor(message, { status = 0, details = [] } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
  }
}

function errorFromPayload(payload, status) {
  const detail = payload?.detail;
  if (typeof detail === 'string') {
    const details = Array.isArray(payload.errors) ? payload.errors.map(String).filter((line) => line !== detail) : [];
    return new ApiError(detail, { status, details });
  }
  if (Array.isArray(detail)) {
    const details = detail.map((item) => [item.loc?.slice(1).join('.'), item.msg].filter(Boolean).join(': '));
    return new ApiError('The server did not accept the request', { status, details });
  }
  return new ApiError(`The server answered with HTTP ${status}`, { status });
}

/** The ApiError for a failed fetch response. */
export async function errorFromResponse(response) {
  const payload = await response.json().catch(() => null);
  return errorFromPayload(payload, response.status);
}

/** JSON request. Resolves to the parsed body, or null for 204. Throws ApiError. */
export async function api(path, { method = 'GET', body } = {}) {
  const init = { method, cache: 'no-store', headers: {} };
  if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError('Cannot reach the workspace server. Is `python -m app` still running?');
  }
  if (response.status === 204) return null;
  if (!response.ok) throw await errorFromResponse(response);
  return response.json();
}

/**
 * Stream one file to the server with a raw PUT. XHR is used for upload progress.
 * onProgress receives a fraction from 0 to 1 while the bytes are sent.
 */
export function uploadFile(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', `/api/uploads/${encodeURIComponent(file.name)}`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch {
          reject(new ApiError(`${file.name}: the server sent an unreadable reply`, { status: xhr.status }));
        }
        return;
      }
      let payload = null;
      try {
        payload = JSON.parse(xhr.responseText);
      } catch {
        // not JSON: fall through with no detail
      }
      reject(errorFromPayload(payload, xhr.status));
    };
    xhr.onerror = () => reject(new ApiError(`${file.name}: the connection dropped, nothing was added`));
    xhr.onabort = () => reject(new ApiError(`${file.name}: the upload was cancelled`));
    xhr.send(file);
  });
}
