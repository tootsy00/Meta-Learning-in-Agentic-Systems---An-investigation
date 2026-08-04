"use client";

import { useI18n } from "@/lib/i18n";
import type { BookCondition, BookWithCategory } from "@/lib/types";
import { buildWhatsAppUrl, formatPriceHkd } from "@/lib/whatsapp";

const CONDITION_STYLES: Record<BookCondition, string> = {
  like_new: "bg-emerald-100 text-emerald-800",
  very_good: "bg-teal-100 text-teal-800",
  good: "bg-sky-100 text-sky-800",
  acceptable: "bg-amber-100 text-amber-800",
  worn: "bg-orange-100 text-orange-900",
};

export function BookCard({ book }: { book: BookWithCategory }) {
  const { lang, t } = useI18n();
  const categoryName =
    lang === "zh" ? book.category_name_zh : book.category_name_en;

  return (
    <article className="flex flex-col overflow-hidden rounded-xl border border-stone-200 bg-white shadow-sm transition-shadow hover:shadow-md">
      <div className="relative aspect-[2/3] bg-stone-200">
        <div className="absolute inset-0 flex items-center justify-center p-4 text-stone-400">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-12 w-12" aria-hidden>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25" />
          </svg>
        </div>
        {book.cover_image && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={book.cover_image}
            alt={book.title}
            loading="lazy"
            className="absolute inset-0 h-full w-full object-cover"
            onError={(e) => {
              e.currentTarget.style.display = "none";
            }}
          />
        )}
        <span
          className={`absolute left-2 top-2 rounded-full px-2 py-0.5 text-[11px] font-semibold ${CONDITION_STYLES[book.condition]}`}
        >
          {t.condition[book.condition]}
        </span>
        {book.status === "reserved" && (
          <span className="absolute right-2 top-2 rounded-full bg-stone-800/85 px-2 py-0.5 text-[11px] font-semibold text-white">
            {t.reserved}
          </span>
        )}
      </div>

      <div className="flex flex-1 flex-col gap-1.5 p-3">
        <h3 className="line-clamp-2 text-sm font-semibold leading-snug text-ink">
          {book.title}
        </h3>
        {book.author && (
          <p className="line-clamp-1 text-xs text-stone-500">{book.author}</p>
        )}
        <div className="mt-auto flex items-center justify-between gap-2 pt-1">
          <span className="text-base font-bold text-amber-800">
            HKD ${formatPriceHkd(book.price_hkd)}
          </span>
          {categoryName && (
            <span className="truncate rounded-full bg-stone-100 px-2 py-0.5 text-[11px] text-stone-600">
              {categoryName}
            </span>
          )}
        </div>
        <a
          href={buildWhatsAppUrl(lang, book)}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 flex items-center justify-center gap-2 rounded-lg bg-[#25D366] px-3 py-2 text-sm font-semibold text-white transition-colors hover:bg-[#1eb85a] active:bg-[#189e4d]"
        >
          <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4" aria-hidden>
            <path d="M12.04 2c-5.46 0-9.91 4.45-9.91 9.91 0 1.75.46 3.45 1.32 4.95L2.05 22l5.25-1.38a9.87 9.87 0 0 0 4.74 1.21c5.46 0 9.91-4.45 9.91-9.91S17.5 2 12.04 2m0 18.03a8.1 8.1 0 0 1-4.13-1.13l-.3-.18-3.12.82.83-3.04-.2-.31a8.08 8.08 0 0 1-1.24-4.28c0-4.47 3.64-8.11 8.16-8.11 4.47 0 8.11 3.64 8.11 8.11s-3.64 8.12-8.11 8.12m4.45-6.07c-.24-.12-1.44-.71-1.66-.79-.22-.08-.39-.12-.55.12-.17.25-.64.79-.78.96-.14.16-.29.18-.54.06-.24-.12-1.03-.38-1.96-1.21-.72-.65-1.21-1.44-1.36-1.68-.14-.25-.01-.38.11-.51.11-.11.25-.29.37-.43.12-.15.16-.25.25-.41.08-.17.04-.31-.02-.43-.06-.12-.55-1.34-.76-1.83-.2-.48-.41-.42-.55-.43h-.47c-.17 0-.43.06-.66.31-.22.25-.86.85-.86 2.07 0 1.22.89 2.4 1.01 2.56.12.17 1.75 2.67 4.23 3.74.59.26 1.05.41 1.41.52.59.19 1.13.16 1.56.1.48-.07 1.44-.59 1.64-1.16.2-.56.2-1.05.14-1.16-.06-.1-.22-.16-.46-.28Z" />
          </svg>
          {t.orderWhatsApp}
        </a>
      </div>
    </article>
  );
}
