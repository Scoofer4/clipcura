import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./styles.css";
import "./i18n";
import { EventsProvider } from "./api/events";
import { ConnectGate } from "./app/ConnectGate";
import { Shell } from "./app/Shell";
import { ToastHost } from "./app/toast";
import { AppearanceProvider } from "./design-system/theme";
import { AboutScreen } from "./screens/AboutScreen";
import { ActivityScreen } from "./screens/ActivityScreen";
import { JobsScreen } from "./screens/JobsScreen";
import { KitchenSink } from "./screens/KitchenSink";
import { ResultsScreen } from "./screens/ResultsScreen";
import { SettingsScreen } from "./screens/SettingsScreen";
import { StartScreen } from "./screens/StartScreen";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AppearanceProvider>
      <BrowserRouter>
        <Routes>
          {/* The design-system reference works without the backend. */}
          <Route path="/_kitchen-sink" element={<KitchenSink />} />
          <Route element={
            <ConnectGate>
              <EventsProvider>
                <ToastHost><Shell /></ToastHost>
              </EventsProvider>
            </ConnectGate>
          }>
            <Route index element={<StartScreen />} />
            <Route path="scans/:scanId" element={<ResultsScreen />} />
            <Route path="jobs" element={<JobsScreen />} />
            <Route path="activity" element={<ActivityScreen />} />
            <Route path="settings" element={<SettingsScreen />} />
            <Route path="about" element={<AboutScreen />} />
            <Route path="*" element={<StartScreen />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AppearanceProvider>
  </React.StrictMode>,
);
