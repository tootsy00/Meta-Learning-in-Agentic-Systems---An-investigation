import { NextRequest, NextResponse } from "next/server";
import { createBook, listBooks } from "@/lib/db";
import { isValidIsbn, normalizeIsbn } from "@/lib/isbn";
import { BOOK_CONDITIONS, type BookCondition, type NewBook } from "@/lib/types";

export const dynamic = "force-dynamic";

export function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const books = listBooks({
    q: params.get("q") ?? undefined,
    category: params.get("category") ?? undefined,
    includeSold: params.get("include_sold") === "1",
  });
  return NextResponse.json({ books });
}

export async function POST(request: NextRequest) {
  let body: Partial<NewBook>;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const isbn = normalizeIsbn(body.isbn ?? "");
  const title = body.title?.trim();
  const price = Number(body.price_hkd);
  const condition = (body.condition ?? "good") as BookCondition;

  if (!isValidIsbn(isbn)) {
    return NextResponse.json({ error: "A valid ISBN-10 or ISBN-13 is required" }, { status: 400 });
  }
  if (!title) {
    return NextResponse.json({ error: "Title is required" }, { status: 400 });
  }
  if (!Number.isFinite(price) || price < 0) {
    return NextResponse.json({ error: "A valid price is required" }, { status: 400 });
  }
  if (!BOOK_CONDITIONS.includes(condition)) {
    return NextResponse.json({ error: "Invalid condition" }, { status: 400 });
  }

  const book = createBook({
    isbn,
    title,
    author: body.author,
    publisher: body.publisher,
    category_id: body.category_id || null,
    condition,
    price_hkd: Math.round(price * 100) / 100,
    shelf_location: body.shelf_location,
    cover_image: body.cover_image,
    description: body.description,
  });
  return NextResponse.json({ book }, { status: 201 });
}
