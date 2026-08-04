-- Lily Bookshop (莉莉書店) — Supabase PostgreSQL schema
-- Run this in the Supabase SQL editor (or `supabase db push`) to provision the database.

-- Enums
CREATE TYPE book_condition AS ENUM ('like_new', 'very_good', 'good', 'acceptable', 'worn');
CREATE TYPE book_status AS ENUM ('in_stock', 'reserved', 'sold');

-- Categories Table
CREATE TABLE categories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name_en TEXT NOT NULL,
  name_zh TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL
);

-- Books Table
CREATE TABLE books (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  isbn VARCHAR(13) NOT NULL,
  title TEXT NOT NULL,
  author TEXT,
  publisher TEXT,
  category_id UUID REFERENCES categories(id),
  condition book_condition DEFAULT 'good',
  price_hkd DECIMAL(10, 2) NOT NULL,
  status book_status DEFAULT 'in_stock',
  shelf_location TEXT, -- e.g., "Fiction-H" or "Box 2"
  cover_image TEXT,
  description TEXT,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Helpful indexes for storefront queries
CREATE INDEX idx_books_status ON books (status);
CREATE INDEX idx_books_category_id ON books (category_id);
CREATE INDEX idx_books_created_at ON books (created_at DESC);

-- Genre seed data (dropdown in the scanner, pills on the storefront)
INSERT INTO categories (name_en, name_zh, slug) VALUES
  ('Fiction',                 '小說',       'fiction'),
  ('Literature',              '文學',       'literature'),
  ('Business',                '商業',       'business'),
  ('History',                 '歷史',       'history'),
  ('Children''s Books',       '兒童讀物',   'childrens'),
  ('Self-Help',               '自我提升',   'self-help'),
  ('Science',                 '科學',       'science'),
  ('Art & Design',            '藝術設計',   'art-design'),
  ('Cookery',                 '飲食烹飪',   'cookery'),
  ('Travel',                  '旅遊',       'travel'),
  ('Philosophy',              '哲學',       'philosophy');
