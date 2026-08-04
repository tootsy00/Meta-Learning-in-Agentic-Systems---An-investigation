import Database from "better-sqlite3";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type {
  Book,
  BookWithCategory,
  Category,
  NewBook,
} from "./types";

// Runtime store for the app. Column names mirror supabase/schema.sql 1:1 so
// the data layer can be swapped to Supabase Postgres without touching callers.
const globalForDb = globalThis as unknown as { __lilyDb?: Database.Database };

function openDb(): Database.Database {
  const dataDir = path.join(process.cwd(), "data");
  fs.mkdirSync(dataDir, { recursive: true });
  const db = new Database(path.join(dataDir, "lily-bookshop.db"));
  db.pragma("journal_mode = WAL");
  db.exec(`
    CREATE TABLE IF NOT EXISTS categories (
      id TEXT PRIMARY KEY,
      name_en TEXT NOT NULL,
      name_zh TEXT NOT NULL,
      slug TEXT UNIQUE NOT NULL
    );
    CREATE TABLE IF NOT EXISTS books (
      id TEXT PRIMARY KEY,
      isbn TEXT NOT NULL,
      title TEXT NOT NULL,
      author TEXT,
      publisher TEXT,
      category_id TEXT REFERENCES categories(id),
      condition TEXT NOT NULL DEFAULT 'good'
        CHECK (condition IN ('like_new', 'very_good', 'good', 'acceptable', 'worn')),
      price_hkd REAL NOT NULL,
      status TEXT NOT NULL DEFAULT 'in_stock'
        CHECK (status IN ('in_stock', 'reserved', 'sold')),
      shelf_location TEXT,
      cover_image TEXT,
      description TEXT,
      created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );
    CREATE INDEX IF NOT EXISTS idx_books_status ON books (status);
    CREATE INDEX IF NOT EXISTS idx_books_category_id ON books (category_id);
  `);

  const insertCategory = db.prepare(
    "INSERT OR IGNORE INTO categories (id, name_en, name_zh, slug) VALUES (?, ?, ?, ?)"
  );
  for (const [name_en, name_zh, slug] of SEED_CATEGORIES) {
    insertCategory.run(randomUUID(), name_en, name_zh, slug);
  }
  return db;
}

const SEED_CATEGORIES: Array<[string, string, string]> = [
  ["Fiction", "小說", "fiction"],
  ["Literature", "文學", "literature"],
  ["Business", "商業", "business"],
  ["History", "歷史", "history"],
  ["Children's Books", "兒童讀物", "childrens"],
  ["Self-Help", "自我提升", "self-help"],
  ["Science", "科學", "science"],
  ["Art & Design", "藝術設計", "art-design"],
  ["Cookery", "飲食烹飪", "cookery"],
  ["Travel", "旅遊", "travel"],
  ["Philosophy", "哲學", "philosophy"],
];

const db = globalForDb.__lilyDb ?? openDb();
globalForDb.__lilyDb = db;

function emptyToNull(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

export function listCategories(): Category[] {
  return db
    .prepare("SELECT id, name_en, name_zh, slug FROM categories ORDER BY name_en")
    .all() as Category[];
}

export function listBooks(opts: {
  q?: string;
  category?: string;
  includeSold?: boolean;
}): BookWithCategory[] {
  const where: string[] = [];
  const params: unknown[] = [];

  if (!opts.includeSold) where.push("b.status != 'sold'");
  if (opts.category) {
    where.push("c.slug = ?");
    params.push(opts.category);
  }
  const q = opts.q?.trim();
  if (q) {
    const ors = ["b.title LIKE ?", "b.author LIKE ?"];
    params.push(`%${q}%`, `%${q}%`);
    const isbnQ = q.replace(/[^0-9Xx]/gi, "");
    if (isbnQ.length >= 3) {
      ors.push("b.isbn LIKE ?");
      params.push(`%${isbnQ}%`);
    }
    where.push(`(${ors.join(" OR ")})`);
  }

  const sql = `
    SELECT b.*, c.name_en AS category_name_en, c.name_zh AS category_name_zh,
           c.slug AS category_slug
    FROM books b
    LEFT JOIN categories c ON c.id = b.category_id
    ${where.length ? `WHERE ${where.join(" AND ")}` : ""}
    ORDER BY b.created_at DESC
  `;
  return db.prepare(sql).all(...params) as BookWithCategory[];
}

export function createBook(input: NewBook): Book {
  const id = randomUUID();
  db.prepare(
    `INSERT INTO books
       (id, isbn, title, author, publisher, category_id, condition, price_hkd,
        status, shelf_location, cover_image, description)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'in_stock', ?, ?, ?)`
  ).run(
    id,
    input.isbn,
    input.title,
    emptyToNull(input.author),
    emptyToNull(input.publisher),
    input.category_id ?? null,
    input.condition,
    input.price_hkd,
    emptyToNull(input.shelf_location),
    emptyToNull(input.cover_image),
    emptyToNull(input.description)
  );
  return db.prepare("SELECT * FROM books WHERE id = ?").get(id) as Book;
}
