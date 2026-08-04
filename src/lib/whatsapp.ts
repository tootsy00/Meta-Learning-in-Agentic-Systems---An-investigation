import type { Lang } from "./i18n";

export const WHATSAPP_NUMBER = "85269775833";

export function formatPriceHkd(price: number): string {
  return Number.isInteger(price) ? String(price) : price.toFixed(2);
}

export function buildWhatsAppUrl(
  lang: Lang,
  book: { title: string; isbn: string; price_hkd: number }
): string {
  const price = formatPriceHkd(book.price_hkd);
  const message =
    lang === "zh"
      ? `莉莉書店你好！我想經 WhatsApp 預留此書（現金面交/自取）：《${book.title}》（ISBN: ${book.isbn}）- 價錢: HKD $${price}。請問有貨嗎？`
      : `Hello Lily Bookshop! I would like to reserve/buy this book for cash pick-up: ${book.title} (ISBN: ${book.isbn}) - Price: HKD $${price}. Is it available?`;
  return `https://wa.me/${WHATSAPP_NUMBER}?text=${encodeURIComponent(message)}`;
}
