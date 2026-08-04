"use client";

import { useEffect, useState } from "react";
import { BookCard } from "@/components/BookCard";
import { LanguageToggle } from "@/components/LanguageToggle";
import { useI18n } from "@/lib/i18n";
import type { BookWithCategory, Category } from "@/lib/types";

export default function Storefront() {
  const { lang, t } = useI18n();
  const [books, setBooks] = useState<BookWithCategory[] | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [activeCategory, setActiveCategory] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/categories")
      .then((r) => r.json())
      .then((d) => setCategories(d.categories))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), 250);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams();
    if (debouncedQuery.trim()) params.set("q", debouncedQuery.trim());
    if (activeCategory) params.set("category", activeCategory);
    fetch(`/api/books?${params}`, { signal: controller.signal })
      .then((r) => r.json())
      .then((d) => setBooks(d.books))
      .catch((err) => {
        if (err.name !== "AbortError") setBooks([]);
      });
    return () => controller.abort();
  }, [debouncedQuery, activeCategory]);

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-stone-200 bg-cream/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-3">
          <a href="/" className="flex shrink-0 items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-full bg-amber-700 text-white">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5" aria-hidden>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25" />
              </svg>
            </span>
            <span className="leading-tight">
              <span className="block font-serif text-base font-bold sm:text-lg">
                Lily Bookshop 莉莉書店
              </span>
              <span className="hidden text-xs text-stone-500 sm:block">
                {t.tagline}
              </span>
            </span>
          </a>

          <div className="relative flex-1">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-stone-400" aria-hidden>
              <path strokeLinecap="round" strokeLinejoin="round" d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" />
            </svg>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t.searchPlaceholder}
              aria-label={t.searchPlaceholder}
              className="w-full rounded-full border border-stone-300 bg-white py-2 pl-9 pr-3 text-base outline-none placeholder:text-stone-400 focus:border-amber-600 focus:ring-2 focus:ring-amber-600/20"
            />
          </div>

          <LanguageToggle />
        </div>
      </header>

      <nav className="mx-auto max-w-6xl px-4 pb-1 pt-4" aria-label="Categories">
        <div className="flex gap-2 overflow-x-auto pb-2">
          <CategoryPill
            label={t.all}
            active={activeCategory === null}
            onClick={() => setActiveCategory(null)}
          />
          {categories.map((c) => (
            <CategoryPill
              key={c.id}
              label={lang === "zh" ? c.name_zh : c.name_en}
              active={activeCategory === c.slug}
              onClick={() => setActiveCategory(c.slug)}
            />
          ))}
        </div>
      </nav>

      <main className="mx-auto max-w-6xl px-4 pb-10">
        {books && (
          <p className="pb-3 text-sm text-stone-500">
            {t.countText(books.length)}
          </p>
        )}
        {books === null ? (
          <p className="py-20 text-center text-stone-500">{t.loading}</p>
        ) : books.length === 0 ? (
          <p className="py-20 text-center text-stone-500">{t.noResults}</p>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-4">
            {books.map((book) => (
              <BookCard key={book.id} book={book} />
            ))}
          </div>
        )}
      </main>

      <footer className="border-t border-stone-200 py-6 text-center text-sm text-stone-500">
        <p>Lily Bookshop 莉莉書店 · {t.footerText}</p>
        <a href="/scan" className="mt-1 inline-block text-xs text-stone-400 underline-offset-2 hover:underline">
          Intake 入書
        </a>
      </footer>
    </div>
  );
}

function CategoryPill({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`shrink-0 rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors ${
        active
          ? "border-amber-700 bg-amber-700 text-white"
          : "border-stone-300 bg-white text-stone-700 hover:border-amber-600 hover:text-amber-800"
      }`}
    >
      {label}
    </button>
  );
}
