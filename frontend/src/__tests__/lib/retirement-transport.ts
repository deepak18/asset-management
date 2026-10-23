import { File as NodeFile } from "node:buffer";
import { vi } from "vitest";

/** jsdom FormData is not serialized by Node fetch. Encode CSV test bodies only,
 * after capturing the real client's options; MSW still handles every response.
 * This adapter is test-only, not a CSV parser or application transport.
 */
export function retirementTransport() {
  const parse = Request.prototype.formData;
  vi.spyOn(Request.prototype, "formData").mockImplementation(async function (
    this: Request,
  ) {
    // Undici's multipart parser constructs global File but requires its own brand.
    const originalFile = globalThis.File;
    globalThis.File = NodeFile as unknown as typeof File;
    try {
      return await parse.call(this);
    } finally {
      globalThis.File = originalFile;
    }
  });
  const fetch = globalThis.fetch;
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (!(init?.body instanceof FormData)) return fetch(input, init);
    const boundary = "slice2b-fictitious-test-boundary";
    let body = "";
    for (const [name, value] of init.body.entries()) {
      body += `--${boundary}\r\nContent-Disposition: form-data; name="${name}"`;
      if (typeof value === "string") body += `\r\n\r\n${value}\r\n`;
      else {
        const text = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result));
          reader.onerror = () => reject(reader.error);
          reader.readAsText(value);
        });
        body += `; filename="${value.name}"\r\nContent-Type: text/csv\r\n\r\n${text}\r\n`;
      }
    }
    body += `--${boundary}--\r\n`;
    const headers = new Headers(init.headers);
    headers.set("Content-Type", `multipart/form-data; boundary=${boundary}`);
    return fetch(input, { ...init, headers, body });
  });
}
