# Lily Bookshop 莉莉書店

Full-stack platform for Lily Bookshop, an independent second-hand bookstore in Hong Kong.

- **Public storefront (`/`)** — browsable/searchable catalog with genre pills, condition badges, English / 繁體中文 toggle, and one-tap **Order via WhatsApp** on every book.
- **Mobile intake scanner (`/scan`)** — un-gated phone page: point the camera at an ISBN barcode, hear a chime, metadata auto-fills from Open Library (Google Books fallback), tap condition + shelf, hit **SAVE & SCAN NEXT**. The camera is back up in under 3 seconds.

## Quick start

```bash
npm install
npm run seed   # optional: 14 sample books so the storefront isn't empty
npm run dev    # http://localhost:3000  (/scan for the intake scanner)
```

Production:

```bash
npm run build && npm start
```

## Stack

- Next.js 15 (App Router) + React 19 + TypeScript + Tailwind CSS
- `@zxing/browser` for camera barcode decoding (EAN-13 / UPC-A, iOS Safari + Android Chrome)
- Server-side ISBN lookup: Open Library → Google Books fallback (`/api/lookup`)

## Database

The app runs out of the box on **SQLite** (`data/lily-bookshop.db`, auto-created, zero config) via a thin data layer in `src/lib/db.ts`.

The production **Supabase PostgreSQL schema** is provided at [`supabase/schema.sql`](supabase/schema.sql) — run it in the Supabase SQL editor to provision the managed database (enums, tables, indexes, category seed). Column names match the SQLite schema 1:1, so migrating the data layer to Supabase (`@supabase/supabase-js`) only touches `src/lib/db.ts`.

## API

| Route | Method | Purpose |
| --- | --- | --- |
| `/api/books?q=&category=` | GET | List in-stock books; `q` matches title / author / ISBN; `category` is a slug; `include_sold=1` shows everything |
| `/api/books` | POST | Create a book (scanner intake) |
| `/api/categories` | GET | List genres |
| `/api/lookup?isbn=` | GET | Fetch title/author/publisher/cover from Open Library, Google Books fallback |

## Notes

- WhatsApp ordering: `https://wa.me/85269775833` with a pre-filled EN or zh-HK message (title, ISBN, price, cash pick-up).
- Language preference persists in `localStorage`; the last-used shelf/box tag is remembered on the intake device for batch scanning.
- The camera requires HTTPS (or localhost) on mobile browsers — deploy behind TLS before using the scanner on the shop floor.
