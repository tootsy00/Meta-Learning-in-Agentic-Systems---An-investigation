"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import type { BookCondition } from "./types";

export type Lang = "en" | "zh";

const en = {
  tagline: "Second-hand books, lovingly curated in Hong Kong",
  searchPlaceholder: "Search title, author or ISBN…",
  all: "All",
  orderWhatsApp: "Order via WhatsApp",
  reserved: "Reserved",
  sold: "Sold",
  condition: {
    like_new: "Like New",
    very_good: "Very Good",
    good: "Good",
    acceptable: "Acceptable",
    worn: "Worn",
  } as Record<BookCondition, string>,
  noResults: "No books found — try another search.",
  loading: "Loading…",
  countText: (n: number) => `${n} book${n === 1 ? "" : "s"} in stock`,
  footerText: "Cash pick-up in store · Order via WhatsApp",
  scanTitle: "Book Intake Scanner",
  startCamera: "START CAMERA",
  pointAtBarcode: "Point the camera at the book's ISBN barcode",
  scanning: "Scanning…",
  lookingUp: "Fetching book details…",
  notFoundManual: "Not found online — fill in the details manually.",
  isbnLabel: "ISBN",
  manualIsbnPlaceholder: "Enter ISBN manually",
  lookupButton: "Look up",
  titleLabel: "Title",
  authorLabel: "Author",
  publisherLabel: "Publisher",
  conditionLabel: "Condition",
  categoryLabel: "Category",
  categoryNone: "Uncategorized",
  priceLabel: "Price (HKD)",
  shelfLabel: "Shelf / Box",
  shelfPlaceholder: "e.g. Fiction-H or Box 2",
  saveNext: "SAVE & SCAN NEXT",
  saving: "Saving…",
  saved: "Saved!",
  saveFailed: "Save failed — please try again.",
  cameraError:
    "Camera unavailable. Check browser permission, or enter the ISBN manually.",
  cancelScan: "Scan a different book",
  backToShop: "Back to shop",
};

export type Dict = typeof en;

const zh: Dict = {
  tagline: "香港二手書 · 精心挑選",
  searchPlaceholder: "搜尋書名、作者或 ISBN…",
  all: "全部",
  orderWhatsApp: "經 WhatsApp 訂購",
  reserved: "已預留",
  sold: "已售出",
  condition: {
    like_new: "近乎全新",
    very_good: "極佳",
    good: "良好",
    acceptable: "尚可",
    worn: "殘舊",
  },
  noResults: "找不到相關書籍，請試試其他關鍵字。",
  loading: "載入中…",
  countText: (n: number) => `共 ${n} 本`,
  footerText: "到店自取 · 現金交收 · 經 WhatsApp 落單",
  scanTitle: "掃描入書",
  startCamera: "啟動相機",
  pointAtBarcode: "將鏡頭對準書本的 ISBN 條碼",
  scanning: "掃描中…",
  lookingUp: "正在查詢書籍資料…",
  notFoundManual: "網上找不到此書，請手動輸入資料。",
  isbnLabel: "ISBN",
  manualIsbnPlaceholder: "手動輸入 ISBN",
  lookupButton: "查詢",
  titleLabel: "書名",
  authorLabel: "作者",
  publisherLabel: "出版社",
  conditionLabel: "書況",
  categoryLabel: "分類",
  categoryNone: "未分類",
  priceLabel: "價錢 (HKD)",
  shelfLabel: "書架 / 箱號",
  shelfPlaceholder: "例如 Fiction-H 或 Box 2",
  saveNext: "儲存並掃描下一本",
  saving: "儲存中…",
  saved: "已儲存！",
  saveFailed: "儲存失敗，請重試。",
  cameraError: "無法啟動相機。請檢查瀏覽器權限，或改用手動輸入 ISBN。",
  cancelScan: "重新掃描",
  backToShop: "返回書店",
};

const DICTS: Record<Lang, Dict> = { en, zh };
const STORAGE_KEY = "lily.lang";

interface I18nContextValue {
  lang: Lang;
  t: Dict;
  setLang: (lang: Lang) => void;
}

const I18nContext = createContext<I18nContextValue>({
  lang: "en",
  t: en,
  setLang: () => {},
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>("en");

  useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "en" || stored === "zh") setLangState(stored);
  }, []);

  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    window.localStorage.setItem(STORAGE_KEY, next);
  }, []);

  return (
    <I18nContext.Provider value={{ lang, t: DICTS[lang], setLang }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n() {
  return useContext(I18nContext);
}
