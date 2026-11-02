import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./styles.css";
import "./i18n";
import { AppearanceProvider } from "./design-system/theme";
import { KitchenSink } from "./screens/KitchenSink";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AppearanceProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/_kitchen-sink" element={<KitchenSink />} />
          {/* Screens arrive in M3b; until then the design system is the app. */}
          <Route path="*" element={<Navigate to="/_kitchen-sink" replace />} />
        </Routes>
      </BrowserRouter>
    </AppearanceProvider>
  </React.StrictMode>,
);
