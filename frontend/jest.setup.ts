// Extends Jest's expect with @testing-library/jest-dom matchers
// (toBeInTheDocument, toHaveTextContent, ...) and registers the global type
// augmentation used by the test files.
import "@testing-library/jest-dom";

// jest-environment-jsdom does not expose TextEncoder/TextDecoder, which the SSE
// stream client (lib/chatStream.ts) relies on to decode the response body.
// Polyfill them from Node's util so the streaming tests run under jsdom.
import { TextDecoder as NodeTextDecoder, TextEncoder as NodeTextEncoder } from "util";

const globalRef = globalThis as unknown as {
  TextDecoder?: typeof TextDecoder;
  TextEncoder?: typeof TextEncoder;
};
if (typeof globalRef.TextDecoder === "undefined") {
  globalRef.TextDecoder = NodeTextDecoder as unknown as typeof TextDecoder;
}
if (typeof globalRef.TextEncoder === "undefined") {
  globalRef.TextEncoder = NodeTextEncoder as unknown as typeof TextEncoder;
}
