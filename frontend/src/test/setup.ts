import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Senza `globals` Vitest non registra la pulizia automatica di Testing Library.
afterEach(() => {
  cleanup();
});
