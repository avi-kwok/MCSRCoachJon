import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { installDirtBackground } from "./dirt";
import "./styles.css";

installDirtBackground();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
