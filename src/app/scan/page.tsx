"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BrowserMultiFormatReader, type IScannerControls } from "@zxing/browser";
import { BarcodeFormat, DecodeHintType } from "@zxing/library";
import { LanguageToggle } from "@/components/LanguageToggle";
import { useI18n } from "@/lib/i18n";
import { isValidIsbn, normalizeIsbn } from "@/lib/isbn";
import {
  BOOK_CONDITIONS,
  type BookCondition,
  type Category,
  type LookupResult,
} from "@/lib/types";

type Phase = "idle" | "scanning" | "loading" | "form" | "saving" | "saved";

const HINTS = new Map<DecodeHintType, unknown>([
  [DecodeHintType.POSSIBLE_FORMATS, [BarcodeFormat.EAN_13, BarcodeFormat.EAN_8, BarcodeFormat.UPC_A]],
  [DecodeHintType.TRY_HARDER, true],
]);

const SUGGESTED_PRICES: Record<BookCondition, number> = {
  like_new: 68,
  very_good: 58,
  good: 45,
  acceptable: 35,
  worn: 25,
};

const CONDITION_BUTTON_STYLES: Record<BookCondition, string> = {
  like_new: "border-emerald-600 bg-emerald-600 text-white",
  very_good: "border-teal-600 bg-teal-600 text-white",
  good: "border-sky-600 bg-sky-600 text-white",
  acceptable: "border-amber-600 bg-amber-600 text-white",
  worn: "border-orange-700 bg-orange-700 text-white",
};

interface FormState {
  isbn: string;
  title: string;
  author: string;
  publisher: string;
  condition: BookCondition;
  categoryId: string;
  price: string;
  shelf: string;
  coverImage: string;
  description: string;
}

function playChime(ctx: AudioContext) {
  const now = ctx.currentTime;
  const gain = ctx.createGain();
  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.exponentialRampToValueAtTime(0.2, now + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.45);
  gain.connect(ctx.destination);
  const osc = ctx.createOscillator();
  osc.type = "sine";
  osc.frequency.setValueAtTime(880, now);
  osc.frequency.setValueAtTime(1318.51, now + 0.11);
  osc.connect(gain);
  osc.start(now);
  osc.stop(now + 0.45);
}

export default function ScanPage() {
  const { t } = useI18n();
  const [phase, setPhase] = useState<Phase>("idle");
  const [cameraError, setCameraError] = useState(false);
  const [lookupMissed, setLookupMissed] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  const [categories, setCategories] = useState<Category[]>([]);
  const [manualIsbn, setManualIsbn] = useState("");
  const [form, setForm] = useState<FormState | null>(null);

  const videoRef = useRef<HTMLVideoElement>(null);
  const controlsRef = useRef<IScannerControls | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const phaseRef = useRef(phase);
  phaseRef.current = phase;

  useEffect(() => {
    fetch("/api/categories")
      .then((r) => r.json())
      .then((d) => setCategories(d.categories))
      .catch(() => {});
    return () => controlsRef.current?.stop();
  }, []);

  const beginIntake = useCallback((isbn: string) => {
    controlsRef.current?.stop();
    controlsRef.current = null;
    setPhase("loading");
    setLookupMissed(false);
    setForm({
      isbn,
      title: "",
      author: "",
      publisher: "",
      condition: "good",
      categoryId: "",
      price: String(SUGGESTED_PRICES.good),
      shelf: window.localStorage.getItem("lily.lastShelf") ?? "",
      coverImage: "",
      description: "",
    });
    fetch(`/api/lookup?isbn=${isbn}`)
      .then(async (r) => {
        if (!r.ok) {
          setLookupMissed(true);
          return null;
        }
        return (await r.json()) as LookupResult;
      })
      .then((d) => {
        if (d?.found) {
          setForm((f) =>
            f
              ? {
                  ...f,
                  title: d.title ?? "",
                  author: d.author ?? "",
                  publisher: d.publisher ?? "",
                  coverImage: d.cover_image ?? "",
                  description: d.description ?? "",
                }
              : f
          );
        }
      })
      .catch(() => setLookupMissed(true))
      .finally(() => setPhase("form"));
  }, []);

  const startScanning = useCallback(async () => {
    setCameraError(false);
    setSaveFailed(false);
    try {
      if (!audioCtxRef.current) {
        const Ctor =
          window.AudioContext ??
          (window as unknown as { webkitAudioContext?: typeof AudioContext })
            .webkitAudioContext;
        if (Ctor) audioCtxRef.current = new Ctor();
      }
      await audioCtxRef.current?.resume();
    } catch {
      // chime is best-effort
    }

    const reader = new BrowserMultiFormatReader(HINTS, {
      delayBetweenScanAttempts: 150,
    });
    try {
      controlsRef.current = await reader.decodeFromConstraints(
        {
          audio: false,
          video: {
            facingMode: { ideal: "environment" },
            width: { ideal: 1280 },
            height: { ideal: 720 },
          },
        },
        videoRef.current!,
        (result) => {
          if (!result || phaseRef.current !== "scanning") return;
          const isbn = normalizeIsbn(result.getText());
          if (!isValidIsbn(isbn)) return; // non-book barcode — keep scanning
          if (audioCtxRef.current) playChime(audioCtxRef.current);
          navigator.vibrate?.(60);
          beginIntake(isbn);
        }
      );
      setPhase("scanning");
    } catch {
      setCameraError(true);
      setPhase("idle");
    }
  }, [beginIntake]);

  const manualLookup = useCallback(() => {
    const isbn = normalizeIsbn(manualIsbn);
    if (!isValidIsbn(isbn)) return;
    setManualIsbn("");
    beginIntake(isbn);
  }, [manualIsbn, beginIntake]);

  const priceNumber = Number(form?.price);
  const canSave =
    !!form &&
    form.title.trim().length > 0 &&
    Number.isFinite(priceNumber) &&
    priceNumber >= 0 &&
    form.price.trim() !== "";

  const save = useCallback(async () => {
    if (!form || !canSave) return;
    setPhase("saving");
    setSaveFailed(false);
    try {
      const res = await fetch("/api/books", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          isbn: form.isbn,
          title: form.title,
          author: form.author,
          publisher: form.publisher,
          category_id: form.categoryId || null,
          condition: form.condition,
          price_hkd: Number(form.price),
          shelf_location: form.shelf,
          cover_image: form.coverImage,
          description: form.description,
        }),
      });
      if (!res.ok) throw new Error();
      window.localStorage.setItem("lily.lastShelf", form.shelf);
      setPhase("saved");
      window.setTimeout(() => startScanning(), 900);
    } catch {
      setSaveFailed(true);
      setPhase("form");
    }
  }, [form, canSave, startScanning]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((f) => (f ? { ...f, [key]: value } : f));

  const pickCondition = (condition: BookCondition) =>
    setForm((f) =>
      f ? { ...f, condition, price: String(SUGGESTED_PRICES[condition]) } : f
    );

  const showCameraArea = phase !== "form" && phase !== "saving";

  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col px-4 pb-6">
      <header className="flex items-center justify-between gap-2 py-3">
        <a href="/" className="text-sm font-medium text-stone-500 hover:text-stone-700">
          ← {t.backToShop}
        </a>
        <h1 className="font-serif text-lg font-bold">{t.scanTitle}</h1>
        <LanguageToggle />
      </header>

      {showCameraArea && (
        <>
          <div className="relative aspect-[4/3] w-full overflow-hidden rounded-2xl bg-stone-900">
            <video
              ref={videoRef}
              muted
              playsInline
              className="h-full w-full object-cover"
            />
            {phase === "idle" && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 p-6 text-center">
                <button
                  type="button"
                  onClick={startScanning}
                  className="rounded-2xl bg-amber-700 px-8 py-4 text-lg font-bold text-white shadow-lg active:bg-amber-800"
                >
                  {t.startCamera}
                </button>
                {cameraError && (
                  <p className="text-sm leading-snug text-red-200">{t.cameraError}</p>
                )}
              </div>
            )}
            {phase === "scanning" && (
              <>
                <div className="pointer-events-none absolute inset-6 rounded-xl border-2 border-dashed border-white/70" />
                <p className="absolute bottom-3 left-0 right-0 text-center text-sm font-medium text-white drop-shadow">
                  {t.pointAtBarcode}
                </p>
                <span className="absolute left-3 top-3 rounded-full bg-black/50 px-2.5 py-1 text-xs font-semibold text-white">
                  {t.scanning}
                </span>
              </>
            )}
            {phase === "loading" && (
              <div className="absolute inset-0 flex items-center justify-center bg-black/60">
                <p className="flex items-center gap-2 text-sm font-semibold text-white">
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
                  {t.lookingUp}
                </p>
              </div>
            )}
            {phase === "saved" && (
              <div className="absolute inset-0 flex items-center justify-center bg-emerald-600/90">
                <p className="flex items-center gap-2 text-2xl font-bold text-white">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" className="h-7 w-7" aria-hidden>
                    <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" />
                  </svg>
                  {t.saved}
                </p>
              </div>
            )}
          </div>

          {(phase === "idle" || phase === "scanning") && (
            <div className="mt-3 flex gap-2">
              <input
                type="text"
                inputMode="numeric"
                value={manualIsbn}
                onChange={(e) => setManualIsbn(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && manualLookup()}
                placeholder={t.manualIsbnPlaceholder}
                aria-label={t.manualIsbnPlaceholder}
                className="min-w-0 flex-1 rounded-xl border border-stone-300 bg-white px-3 py-2.5 text-base outline-none focus:border-amber-600 focus:ring-2 focus:ring-amber-600/20"
              />
              <button
                type="button"
                onClick={manualLookup}
                disabled={!isValidIsbn(normalizeIsbn(manualIsbn))}
                className="shrink-0 rounded-xl bg-stone-800 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-40"
              >
                {t.lookupButton}
              </button>
            </div>
          )}
        </>
      )}

      {form && (phase === "form" || phase === "saving") && (
        <div className="mt-2 flex flex-col gap-3">
          <div className="flex items-center gap-3 rounded-xl border border-stone-200 bg-white p-3">
            <div className="relative h-20 w-14 shrink-0 overflow-hidden rounded-md bg-stone-200">
              {form.coverImage && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={form.coverImage}
                  alt=""
                  className="h-full w-full object-cover"
                  onError={(e) => {
                    e.currentTarget.style.display = "none";
                  }}
                />
              )}
            </div>
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-wide text-stone-500">
                {t.isbnLabel}
              </p>
              <p className="font-mono text-sm font-semibold">{form.isbn}</p>
              {lookupMissed && (
                <p className="mt-1 text-xs leading-snug text-amber-800">
                  {t.notFoundManual}
                </p>
              )}
            </div>
          </div>

          <label className="block">
            <span className="mb-1 block text-xs font-semibold text-stone-600">{t.titleLabel}</span>
            <input
              type="text"
              value={form.title}
              onChange={(e) => update("title", e.target.value)}
              className="w-full rounded-xl border border-stone-300 bg-white px-3 py-2.5 text-base outline-none focus:border-amber-600 focus:ring-2 focus:ring-amber-600/20"
            />
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-semibold text-stone-600">{t.authorLabel}</span>
            <input
              type="text"
              value={form.author}
              onChange={(e) => update("author", e.target.value)}
              className="w-full rounded-xl border border-stone-300 bg-white px-3 py-2.5 text-base outline-none focus:border-amber-600 focus:ring-2 focus:ring-amber-600/20"
            />
          </label>

          <div>
            <span className="mb-1 block text-xs font-semibold text-stone-600">{t.conditionLabel}</span>
            <div className="grid grid-cols-5 gap-1.5">
              {BOOK_CONDITIONS.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => pickCondition(c)}
                  aria-pressed={form.condition === c}
                  className={`rounded-lg border px-1 py-2 text-[11px] font-semibold leading-tight transition-colors ${
                    form.condition === c
                      ? CONDITION_BUTTON_STYLES[c]
                      : "border-stone-300 bg-white text-stone-600"
                  }`}
                >
                  {t.condition[c]}
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="mb-1 block text-xs font-semibold text-stone-600">{t.priceLabel}</span>
              <input
                type="number"
                inputMode="decimal"
                min="0"
                step="1"
                value={form.price}
                onChange={(e) => update("price", e.target.value)}
                className="w-full rounded-xl border border-stone-300 bg-white px-3 py-2.5 text-base font-semibold outline-none focus:border-amber-600 focus:ring-2 focus:ring-amber-600/20"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-semibold text-stone-600">{t.categoryLabel}</span>
              <select
                value={form.categoryId}
                onChange={(e) => update("categoryId", e.target.value)}
                className="w-full rounded-xl border border-stone-300 bg-white px-3 py-2.5 text-base outline-none focus:border-amber-600 focus:ring-2 focus:ring-amber-600/20"
              >
                <option value="">{t.categoryNone}</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name_en} {c.name_zh}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="block">
            <span className="mb-1 block text-xs font-semibold text-stone-600">{t.shelfLabel}</span>
            <input
              type="text"
              value={form.shelf}
              onChange={(e) => update("shelf", e.target.value)}
              placeholder={t.shelfPlaceholder}
              className="w-full rounded-xl border border-stone-300 bg-white px-3 py-2.5 text-base outline-none focus:border-amber-600 focus:ring-2 focus:ring-amber-600/20"
            />
          </label>

          {saveFailed && (
            <p className="text-sm font-medium text-red-700">{t.saveFailed}</p>
          )}

          <div className="mt-1 flex gap-2">
            <button
              type="button"
              onClick={startScanning}
              className="shrink-0 rounded-xl border border-stone-300 bg-white px-4 py-3.5 text-sm font-semibold text-stone-600"
            >
              {t.cancelScan}
            </button>
            <button
              type="button"
              onClick={save}
              disabled={!canSave || phase === "saving"}
              className="flex-1 rounded-xl bg-amber-700 py-3.5 text-lg font-bold text-white shadow active:bg-amber-800 disabled:opacity-40"
            >
              {phase === "saving" ? t.saving : t.saveNext}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
