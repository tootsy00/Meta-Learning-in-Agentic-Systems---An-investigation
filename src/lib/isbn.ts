/** Normalize a raw barcode / typed ISBN: strip separators, uppercase X. */
export function normalizeIsbn(raw: string): string {
  return raw.replace(/[^0-9Xx]/g, "").toUpperCase();
}

/** Valid ISBN-10 or ISBN-13 (checksum not enforced — worn barcodes still scan). */
export function isValidIsbn(isbn: string): boolean {
  return /^\d{10}$|^\d{9}X$|^\d{13}$/.test(isbn);
}
