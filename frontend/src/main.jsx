import React from "react";
import { createRoot } from "react-dom/client";

// One variable face carries the whole system — every weight from one file.
import "@fontsource-variable/manrope";
// Mono is reserved for machine identifiers — resource IDs, usage types, ARNs.
import "@fontsource/jetbrains-mono/400.css";

import "./styles.css";
import App from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
);
