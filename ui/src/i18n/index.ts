import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./en.json";
import cs from "./cs.json";

export const LANGUAGES = ["en", "cs"] as const;
export type Language = (typeof LANGUAGES)[number];

function initialLanguage(): Language {
  const fromUrl = new URLSearchParams(window.location.search).get("lang");
  if (fromUrl === "en" || fromUrl === "cs") return fromUrl;
  try {
    const saved = localStorage.getItem("clipcura.lang");
    if (saved === "en" || saved === "cs") return saved;
  } catch {
    /* storage unavailable */
  }
  return "en"; // English by default (CLAUDE.md §2), Czech as a translation
}

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, cs: { translation: cs } },
  lng: initialLanguage(),
  fallbackLng: "en",
  interpolation: { escapeValue: false }, // React escapes already
});

export function setLanguage(lang: Language) {
  void i18n.changeLanguage(lang);
  document.documentElement.lang = lang;
  try {
    localStorage.setItem("clipcura.lang", lang);
  } catch {
    /* non-essential */
  }
}

export default i18n;
