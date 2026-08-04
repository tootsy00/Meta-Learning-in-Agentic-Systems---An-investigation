"use client";

import { useI18n } from "@/lib/i18n";

export function LanguageToggle() {
  const { lang, setLang } = useI18n();
  const base = "rounded-full px-2.5 py-1 text-xs font-semibold transition-colors";
  return (
    <div className="flex shrink-0 rounded-full border border-stone-300 bg-white p-0.5">
      <button
        type="button"
        aria-pressed={lang === "en"}
        onClick={() => setLang("en")}
        className={`${base} ${lang === "en" ? "bg-amber-700 text-white" : "text-stone-600"}`}
      >
        EN
      </button>
      <button
        type="button"
        aria-pressed={lang === "zh"}
        onClick={() => setLang("zh")}
        className={`${base} ${lang === "zh" ? "bg-amber-700 text-white" : "text-stone-600"}`}
      >
        繁體中文
      </button>
    </div>
  );
}
