import { ReactNode, useCallback, useEffect, useState } from "react";
import { ApiError, Outcome } from "./api";

export const OUTCOME: Record<Outcome, { icon: string; text: string }> = {
  done: { icon: "✓", text: "выполнено" },
  partial: { icon: "½", text: "частично" },
  not_done: { icon: "✗", text: "не выполнено" },
};

const WD = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];

export function dayTitle(iso: string): string {
  const d = new Date(iso + "T12:00:00");
  return `${WD[d.getDay()]} ${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export function timeOf(iso: string): string {
  return new Date(iso).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

export function dateTimeOf(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function navigate(to: string) {
  location.hash = to;
}

export function useHash(): string {
  const [h, setH] = useState(location.hash.slice(1) || "/");
  useEffect(() => {
    const on = () => setH(location.hash.slice(1) || "/");
    addEventListener("hashchange", on);
    return () => removeEventListener("hashchange", on);
  }, []);
  return h;
}

/** Загрузка данных с перезагрузкой по требованию. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => {
    fn()
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: ApiError) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(reload, [reload]);
  return { data, error, reload, setData };
}

export function Header({ title, back, right }: { title: string; back?: string | boolean; right?: ReactNode }) {
  return (
    <header className="hdr">
      {back && (
        <button className="back" onClick={() => (typeof back === "string" ? navigate(back) : history.back())} aria-label="Назад">
          ←
        </button>
      )}
      <h1>{title}</h1>
      <div className="hdr-right">{right}</div>
    </header>
  );
}

export function Chips<T extends string>({ options, value, onChange }: { options: [T, string][]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="chips">
      {options.map(([v, label]) => (
        <button key={v} type="button" className={`chip ${v === value ? "on" : ""}`} onClick={() => onChange(v)}>
          {label}
        </button>
      ))}
    </div>
  );
}

export function Field({ label, children, group }: { label: string; children: ReactNode; group?: boolean }) {
  // Группа кнопок не может жить внутри <label>: клик по подписи нажал бы первую кнопку.
  if (group)
    return (
      <div className="field" role="group" aria-label={label}>
        <span>{label}</span>
        {children}
      </div>
    );
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

export function Note({ children }: { children: ReactNode }) {
  return <div className="note">{children}</div>;
}

export function ErrorBox({ error }: { error: string | null }) {
  return error ? <div className="err">{error}</div> : null;
}

/** Обёртка для команд: блокирует повторный клик и показывает ошибку. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run, setError };
}

export const RELATIONS: [string, string][] = [
  ["father", "папа"],
  ["mother", "мама"],
  ["guardian", "опекун"],
  ["other", "другое"],
];
