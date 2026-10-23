/** Browser entry point for the Journal Library interface. */
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

/** Mount the single-page app into the root element created by Vite. */
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
