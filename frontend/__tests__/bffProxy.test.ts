/**
 * @jest-environment node
 */
import { NextRequest } from "next/server";

import { proxyRequest } from "@/lib/bffProxy";

/** Build a JWT-shaped token whose base64url payload carries the given claims. */
function makeToken(payload: Record<string, unknown>): string {
  const seg = (obj: unknown) =>
    Buffer.from(JSON.stringify(obj)).toString("base64url");
  return `${seg({ alg: "HS256" })}.${seg(payload)}.sig`;
}

const nowSec = Math.floor(Date.now() / 1000);
const TOKEN = makeToken({ sub: "u", role: "user", sid: "sid-1", exp: nowSec + 3600 });

const ENV = { INTERNAL_API_URL: "http://backend:8000" };

describe("proxyRequest", () => {
  it("injects Authorization from the cookie and strips client-supplied auth/cookie headers", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(new Response("ok", { status: 200 }));
    const request = new NextRequest("http://localhost:3000/api/chat?x=1", {
      method: "POST",
      headers: {
        cookie: `cc_session=${TOKEN}`,
        authorization: "Bearer client-forged",
        "content-type": "application/json",
      },
      body: JSON.stringify({ message: "hi" }),
    });

    await proxyRequest(request, { fetchImpl, env: ENV });

    const [target, init] = fetchImpl.mock.calls[0];
    expect(target).toBe("http://backend:8000/api/chat?x=1");
    const headers = init.headers as Headers;
    // The BFF sets Authorization from the cookie, overriding any client-supplied value.
    expect(headers.get("authorization")).toBe(`Bearer ${TOKEN}`);
    // The browser cookie is never forwarded to the backend.
    expect(headers.get("cookie")).toBeNull();
    expect(init.method).toBe("POST");
  });

  it("sends no Authorization when there is no session cookie", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(new Response("ok", { status: 200 }));
    const request = new NextRequest("http://localhost:3000/api/chat", {
      method: "POST",
      body: "{}",
      headers: { "content-type": "application/json" },
    });

    await proxyRequest(request, { fetchImpl, env: ENV });

    const [, init] = fetchImpl.mock.calls[0];
    expect((init.headers as Headers).get("authorization")).toBeNull();
  });

  it("streams the backend SSE body straight through without buffering", async () => {
    const frames = [
      'event: start\ndata: {"message_id":"m1"}\n\n',
      'event: token\ndata: {"content":"Hi"}\n\n',
    ];
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        const enc = new TextEncoder();
        for (const f of frames) {
          controller.enqueue(enc.encode(f));
        }
        controller.close();
      },
    });
    const fetchImpl = jest.fn().mockResolvedValue(
      new Response(stream, {
        status: 200,
        headers: { "content-type": "text/event-stream" },
      }),
    );
    const request = new NextRequest("http://localhost:3000/api/chat", {
      method: "POST",
      body: "{}",
      headers: { "content-type": "application/json" },
    });

    const response = await proxyRequest(request, { fetchImpl, env: ENV });

    // The SSE content-type survives, and the body is a live ReadableStream (not buffered).
    expect(response.headers.get("content-type")).toBe("text/event-stream");
    expect(response.body).toBeInstanceOf(ReadableStream);
    expect(await response.text()).toBe(frames.join(""));
  });

  it("forwards DELETE /api/me with the cookie Authorization and no body (SEC-05 erasure)", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }));
    const request = new NextRequest("http://localhost:3000/api/me", {
      method: "DELETE",
      headers: { cookie: `cc_session=${TOKEN}` },
    });

    const response = await proxyRequest(request, { fetchImpl, env: ENV });

    const [target, init] = fetchImpl.mock.calls[0];
    // The erasure DELETE reaches the backend /api/me path, not a bypass, with the token injected.
    expect(target).toBe("http://backend:8000/api/me");
    expect(init.method).toBe("DELETE");
    // A bodyless DELETE forwards the request's (null) body — no client payload to stream.
    expect(init.body ?? null).toBeNull();
    expect((init.headers as Headers).get("authorization")).toBe(`Bearer ${TOKEN}`);
    expect(response.status).toBe(204);
  });

  it("passes GET /api/me/export through with its download disposition header (SEC-05 export)", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(
      new Response('{"user":null}', {
        status: 200,
        headers: {
          "content-type": "application/json",
          "content-disposition": 'attachment; filename="career-coach-export.json"',
        },
      }),
    );
    const request = new NextRequest("http://localhost:3000/api/me/export", {
      method: "GET",
      headers: { cookie: `cc_session=${TOKEN}` },
    });

    const response = await proxyRequest(request, { fetchImpl, env: ENV });

    const [target] = fetchImpl.mock.calls[0];
    expect(target).toBe("http://backend:8000/api/me/export");
    // The attachment disposition survives the proxy so the browser downloads the export file.
    expect(response.headers.get("content-disposition")).toBe(
      'attachment; filename="career-coach-export.json"',
    );
  });

  it("does not send a body for GET requests", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(new Response("ok", { status: 200 }));
    const request = new NextRequest("http://localhost:3000/api/profile", {
      method: "GET",
      headers: { cookie: `cc_session=${TOKEN}` },
    });

    await proxyRequest(request, { fetchImpl, env: ENV });

    const [, init] = fetchImpl.mock.calls[0];
    expect(init.body).toBeUndefined();
    expect((init.headers as Headers).get("authorization")).toBe(`Bearer ${TOKEN}`);
  });
});
