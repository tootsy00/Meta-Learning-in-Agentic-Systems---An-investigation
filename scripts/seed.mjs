// Seed sample inventory so the storefront is browsable out of the box.
// Usage: npm run seed   (idempotent — skips ISBNs that already exist)
import Database from "better-sqlite3";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";

const dataDir = path.join(process.cwd(), "data");
fs.mkdirSync(dataDir, { recursive: true });
const db = new Database(path.join(dataDir, "lily-bookshop.db"));

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
`);
const seedCategory = db.prepare(
  "INSERT OR IGNORE INTO categories (id, name_en, name_zh, slug) VALUES (?, ?, ?, ?)"
);
for (const [en, zh, slug] of [
  ["Fiction", "小說", "fiction"], ["Literature", "文學", "literature"],
  ["Business", "商業", "business"], ["History", "歷史", "history"],
  ["Children's Books", "兒童讀物", "childrens"], ["Self-Help", "自我提升", "self-help"],
  ["Science", "科學", "science"], ["Art & Design", "藝術設計", "art-design"],
  ["Cookery", "飲食烹飪", "cookery"], ["Travel", "旅遊", "travel"],
  ["Philosophy", "哲學", "philosophy"],
]) seedCategory.run(randomUUID(), en, zh, slug);

const cover = (isbn) => `https://covers.openlibrary.org/b/isbn/${isbn}-M.jpg`;

const BOOKS = [
  ["9780747532699", "Harry Potter and the Philosopher's Stone", "J.K. Rowling", "Bloomsbury", "fiction", "very_good", 55, "Fiction-H"],
  ["9780439708180", "Harry Potter and the Sorcerer's Stone", "J.K. Rowling", "Scholastic", "fiction", "good", 45, "Fiction-H"],
  ["9780451524935", "1984", "George Orwell", "Signet Classics", "fiction", "good", 40, "Fiction-O"],
  ["9780141439518", "Pride and Prejudice", "Jane Austen", "Penguin Classics", "literature", "like_new", 60, "Lit-A"],
  ["9780061120084", "To Kill a Mockingbird", "Harper Lee", "Grand Central", "literature", "acceptable", 30, "Lit-L"],
  ["9780307277671", "The Kite Runner", "Khaled Hosseini", "Riverhead Books", "fiction", "good", 42, "Fiction-H"],
  ["9780062315007", "The Alchemist", "Paulo Coelho", "HarperOne", "fiction", "very_good", 50, "Fiction-C"],
  ["9780261103573", "The Hobbit", "J.R.R. Tolkien", "HarperCollins", "fiction", "worn", 25, "Fiction-T"],
  ["9780156012195", "The Little Prince", "Antoine de Saint-Exupéry", "Mariner Books", "childrens", "good", 38, "Kids-1"],
  ["9780735211292", "Atomic Habits", "James Clear", "Avery", "self-help", "like_new", 70, "SH-A"],
  ["9780374533557", "Thinking, Fast and Slow", "Daniel Kahneman", "FSG", "science", "good", 48, "Sci-K"],
  ["9780307887436", "The Lean Startup", "Eric Ries", "Currency", "business", "very_good", 52, "Biz-1"],
  ["9780671027032", "How to Win Friends and Influence People", "Dale Carnegie", "Pocket Books", "business", "acceptable", 28, "Biz-2"],
  ["9787506365437", "活著 (To Live)", "余華", "作家出版社", "literature", "good", 45, "ZH-1"],
];

const STATUS_OVERRIDES = { "9780451524935": "reserved", "9780261103573": "sold" };

const findCategory = db.prepare("SELECT id FROM categories WHERE slug = ?");
const exists = db.prepare("SELECT 1 FROM books WHERE isbn = ?");
const insert = db.prepare(
  `INSERT INTO books (id, isbn, title, author, publisher, category_id, condition, price_hkd, status, shelf_location, cover_image)
   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
);

let added = 0;
for (const [isbn, title, author, publisher, slug, condition, price, shelf] of BOOKS) {
  if (exists.get(isbn)) continue;
  const category = findCategory.get(slug);
  insert.run(
    randomUUID(), isbn, title, author, publisher,
    category?.id ?? null, condition, price,
    STATUS_OVERRIDES[isbn] ?? "in_stock", shelf, cover(isbn)
  );
  added++;
}
console.log(`Seed complete: ${added} book(s) added, ${BOOKS.length - added} already present.`);
