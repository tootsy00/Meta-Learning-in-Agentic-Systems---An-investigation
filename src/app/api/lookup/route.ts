import { NextRequest, NextResponse } from "next/server";
import { isValidIsbn, normalizeIsbn } from "@/lib/isbn";
import type { LookupResult } from "@/lib/types";

export const dynamic = "force-dynamic";

const OL_TIMEOUT = 6000;
const GB_TIMEOUT = 8000;

// Primary: Open Library Books API (per spec)
async function fromOpenLibraryData(isbn: string): Promise<LookupResult | null> {
  const url = `https://openlibrary.org/api/books?bibkeys=ISBN:${isbn}&format=json&jscmd=data`;
  const res = await fetch(url, { signal: AbortSignal.timeout(OL_TIMEOUT), cache: "no-store" });
  if (!res.ok) return null;
  const data = await res.json();
  const entry = data[`ISBN:${isbn}`];
  if (!entry?.title) return null;
  return {
    found: true,
    isbn,
    title: entry.title,
    author: entry.authors?.map((a: { name: string }) => a.name).join(", ") || undefined,
    publisher: entry.publishers?.[0]?.name || undefined,
    cover_image:
      entry.cover?.medium ?? `https://covers.openlibrary.org/b/isbn/${isbn}-M.jpg`,
    source: "openlibrary",
  };
}

// Fallback 1: Open Library edition record (different endpoint, separate availability)
async function fromOpenLibraryEdition(isbn: string): Promise<LookupResult | null> {
  const res = await fetch(`https://openlibrary.org/isbn/${isbn}.json`, {
    signal: AbortSignal.timeout(OL_TIMEOUT),
    cache: "no-store",
  });
  if (!res.ok) return null;
  const edition = await res.json();
  if (!edition?.title) return null;

  let authorKeys: string[] = (edition.authors ?? [])
    .map((a: { key?: string }) => a?.key)
    .filter(Boolean);

  // Editions often link authors only via their parent work record
  if (authorKeys.length === 0 && edition.works?.[0]?.key) {
    try {
      const workRes = await fetch(`https://openlibrary.org${edition.works[0].key}.json`, {
        signal: AbortSignal.timeout(4000),
        cache: "no-store",
      });
      if (workRes.ok) {
        const work = await workRes.json();
        authorKeys = (work.authors ?? [])
          .map((a: { author?: { key?: string } }) => a?.author?.key)
          .filter(Boolean);
      }
    } catch {
      // fall through to by_statement
    }
  }

  let author: string | undefined;
  if (authorKeys.length > 0) {
    const names = await Promise.all(
      authorKeys.slice(0, 2).map(async (key) => {
        try {
          const r = await fetch(`https://openlibrary.org${key}.json`, {
            signal: AbortSignal.timeout(4000),
            cache: "no-store",
          });
          return r.ok ? ((await r.json())?.name as string | undefined) : undefined;
        } catch {
          return undefined;
        }
      })
    );
    author = names.filter(Boolean).join(", ") || undefined;
  }
  if (!author && typeof edition.by_statement === "string") {
    author = edition.by_statement;
  }

  const coverId = Array.isArray(edition.covers) ? edition.covers[0] : undefined;
  const description =
    typeof edition.description === "string"
      ? edition.description
      : edition.description?.value;

  return {
    found: true,
    isbn,
    title: edition.title,
    author,
    publisher: edition.publishers?.[0] || undefined,
    cover_image: coverId
      ? `https://covers.openlibrary.org/b/id/${coverId}-M.jpg`
      : `https://covers.openlibrary.org/b/isbn/${isbn}-M.jpg`,
    description: description || undefined,
    source: "openlibrary",
  };
}

// Fallback 2: Google Books
async function fromGoogleBooks(isbn: string): Promise<LookupResult | null> {
  const url = `https://www.googleapis.com/books/v1/volumes?q=isbn:${isbn}`;
  const res = await fetch(url, { signal: AbortSignal.timeout(GB_TIMEOUT), cache: "no-store" });
  if (!res.ok) return null;
  const data = await res.json();
  const info = data.items?.[0]?.volumeInfo;
  if (!info?.title) return null;
  return {
    found: true,
    isbn,
    title: info.title,
    author: info.authors?.join(", ") || undefined,
    publisher: info.publisher || undefined,
    cover_image: info.imageLinks?.thumbnail?.replace(/^http:\/\//, "https://") || undefined,
    description: info.description || undefined,
    source: "googlebooks",
  };
}

export async function GET(request: NextRequest) {
  const isbn = normalizeIsbn(request.nextUrl.searchParams.get("isbn") ?? "");
  if (!isValidIsbn(isbn)) {
    return NextResponse.json({ error: "A valid ISBN-10 or ISBN-13 is required" }, { status: 400 });
  }

  const result =
    (await fromOpenLibraryData(isbn).catch(() => null)) ??
    (await fromOpenLibraryEdition(isbn).catch(() => null)) ??
    (await fromGoogleBooks(isbn).catch(() => null));

  if (!result) {
    return NextResponse.json({ found: false, isbn } satisfies LookupResult, { status: 404 });
  }
  return NextResponse.json(result);
}
