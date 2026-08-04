export type BookCondition =
  | "like_new"
  | "very_good"
  | "good"
  | "acceptable"
  | "worn";

export type BookStatus = "in_stock" | "reserved" | "sold";

export const BOOK_CONDITIONS: BookCondition[] = [
  "like_new",
  "very_good",
  "good",
  "acceptable",
  "worn",
];

export interface Category {
  id: string;
  name_en: string;
  name_zh: string;
  slug: string;
}

export interface Book {
  id: string;
  isbn: string;
  title: string;
  author: string | null;
  publisher: string | null;
  category_id: string | null;
  condition: BookCondition;
  price_hkd: number;
  status: BookStatus;
  shelf_location: string | null;
  cover_image: string | null;
  description: string | null;
  created_at: string;
}

export interface BookWithCategory extends Book {
  category_name_en: string | null;
  category_name_zh: string | null;
  category_slug: string | null;
}

export interface NewBook {
  isbn: string;
  title: string;
  author?: string | null;
  publisher?: string | null;
  category_id?: string | null;
  condition: BookCondition;
  price_hkd: number;
  shelf_location?: string | null;
  cover_image?: string | null;
  description?: string | null;
}

export interface LookupResult {
  found: boolean;
  isbn: string;
  title?: string;
  author?: string;
  publisher?: string;
  cover_image?: string;
  description?: string;
  source?: "openlibrary" | "googlebooks";
}
