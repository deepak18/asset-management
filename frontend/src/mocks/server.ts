import { setupServer } from "msw/node";
import { handlers } from "@/mocks/handlers";

/**
 * Node-side MSW server used by Vitest (see vitest.setup.ts). It intercepts
 * `fetch` during tests so components run against the contract fixtures with no
 * live backend. `onUnhandledRequest: "error"` in the setup makes any un-mocked
 * call fail loudly rather than leak to the network.
 */
export const server = setupServer(...handlers);
