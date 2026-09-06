import React from "react";
import { createRoot } from "react-dom/client";

// Same two faces as the dashboard, loaded the same way.
import "@fontsource-variable/manrope";
import "@fontsource/jetbrains-mono/400.css";

import "./landing.css";
import App from "./App";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
