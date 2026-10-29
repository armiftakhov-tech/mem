export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function csrf(): string {
  const m = document.cookie.match(/(?:^|; )discipline_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

export async function api<T = any>(method: string, path: string, body?: unknown): Promise<T> {
  let r: Response;
  try {
    r = await fetch(`/api${path}`, {
      method,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf() },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Нет связи с сервером. Изменения не сохранены.");
  }
  if (r.ok) return r.json();
  let msg = `Ошибка ${r.status}`;
  try {
    const j = await r.json();
    if (typeof j.detail === "string") msg = j.detail;
    else if (Array.isArray(j.detail)) msg = j.detail.map((d: any) => String(d.msg).replace(/^Value error, /, "")).join("; ");
  } catch {
    /* не JSON */
  }
  throw new ApiError(r.status, msg);
}

export const get = <T = any>(p: string) => api<T>("GET", p);
export const post = <T = any>(p: string, b?: unknown) => api<T>("POST", p, b ?? {});
export const patch = <T = any>(p: string, b: unknown) => api<T>("PATCH", p, b);
export const put = <T = any>(p: string, b: unknown) => api<T>("PUT", p, b);
export const del = <T = any>(p: string) => api<T>("DELETE", p);

export const newKey = () => crypto.randomUUID().replace(/-/g, "");

export type Review = { id: string; outcome: Outcome; reviewer_name: string; reviewed_at: string; is_current: boolean; corrects: boolean };
export type Outcome = "done" | "partial" | "not_done";
export type Assignment = {
  id: string;
  child_id: string;
  child_name: string;
  text: string;
  success_criteria: string | null;
  date: string;
  due_time: string;
  check_time: string;
  state: "active" | "closed" | "cancelled";
  overdue: boolean;
  due_passed: boolean;
  version: number;
  recurrence_id: string | null;
  recurrence_text: string | null;
  created_by_name: string | null;
  closed_at: string | null;
  cancelled_at: string | null;
  cancelled_by_name?: string;
  current_review: Review | null;
  child_marked_at: string | null;
  comments_count: number;
  reviews?: Review[];
  comments?: { id: string; text: string; author_name: string; by_child: boolean; created_at: string }[];
};
export type Me = {
  kind: "parent" | "child";
  login: string;
  family: { id: string; timezone: string };
  today: string;
  parent?: { id: string; name: string };
  child?: { id: string; name: string };
  children?: { id: string; name: string }[];
};
