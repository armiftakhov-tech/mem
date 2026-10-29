import { useState } from "react";
import { Assignment, Me, Outcome, get, newKey, patch, post } from "./api";
import { Chips, ErrorBox, Field, Header, Note, OUTCOME, dateTimeOf, dayTitle, navigate, timeOf, useAction, useLoad } from "./ui";

export function Bell({ unread }: { unread: number }) {
  return (
    <a className="bell" href="#/notifications">
      🔔 {unread}
    </a>
  );
}

function ChildFilter({ me, value, onChange }: { me: Me; value: string; onChange: (v: string) => void }) {
  const opts: [string, string][] = [["", "Все"], ...(me.children ?? []).map((c): [string, string] => [c.id, c.name])];
  return opts.length > 2 ? <Chips options={opts} value={value} onChange={onChange} /> : null;
}

function Badge({ a }: { a: Assignment }) {
  if (a.state === "cancelled") return <span className="badge">отменено</span>;
  if (a.current_review) {
    const o = OUTCOME[a.current_review.outcome];
    return (
      <span className={`badge o-${a.current_review.outcome}`}>
        {o.icon} {o.text}
      </span>
    );
  }
  return (
    <>
      {a.overdue && <span className="badge dark">просрочено</span>}
      {a.child_marked_at && <span className="badge">ребёнок: сделал</span>}
    </>
  );
}

export function Card({ a, showChild = true, href }: { a: Assignment; showChild?: boolean; href: string }) {
  const meta = [showChild ? a.child_name : null, a.due_time !== a.check_time ? `срок ${a.due_time}` : null, `проверка ${a.check_time}`]
    .filter(Boolean)
    .join(" · ");
  return (
    <a className="card" href={href}>
      <b>{a.text}</b>
      <div className="meta">
        {meta}
        {a.recurrence_text && <span className="badge">↻ {a.recurrence_text}</span>}
        {a.comments_count > 0 && <span className="badge">💬 {a.comments_count}</span>}
        <Badge a={a} />
      </div>
    </a>
  );
}

export function Today({ me, unread }: { me: Me; unread: number }) {
  const [child, setChild] = useState("");
  const { data, error } = useLoad(() => get<Assignment[]>(`/assignments/today${child ? `?child_id=${child}` : ""}`), [child, unread]);
  const list = data ?? [];
  const toCheck = list.filter((a) => a.state === "active" && a.due_passed);
  const later = list.filter((a) => a.state === "active" && !a.due_passed);
  const checked = list.filter((a) => a.state === "closed");
  return (
    <div className="screen">
      <Header title={`Сегодня, ${dayTitle(me.today)}`} right={<Bell unread={unread} />} />
      <ChildFilter me={me} value={child} onChange={setChild} />
      <ErrorBox error={error} />
      {data && list.length === 0 && <p className="muted">На сегодня заданий нет. Нажмите +, чтобы дать задание.</p>}
      <Section title="Пора проверить" items={toCheck} />
      <Section title="Позже сегодня" items={later} />
      <Section title="Проверено" items={checked} />
      <a className="fab" href="#/new" aria-label="Новое задание">
        +
      </a>
    </div>
  );
}

function Section({ title, items }: { title: string; items: Assignment[] }) {
  if (!items.length) return null;
  return (
    <>
      <h3>
        {title} ({items.length})
      </h3>
      {items.map((a) => (
        <Card key={a.id} a={a} href={`#/a/${a.id}`} />
      ))}
    </>
  );
}

const WEEK: [number, string][] = [
  [0, "пн"],
  [1, "вт"],
  [2, "ср"],
  [3, "чт"],
  [4, "пт"],
  [5, "сб"],
  [6, "вс"],
];

export function AssignmentForm({ me, edit }: { me: Me; edit?: Assignment }) {
  const kids = me.children ?? [];
  const [key] = useState(newKey);
  const [f, setF] = useState({
    child_id: edit?.child_id ?? kids[0]?.id ?? "",
    text: edit?.text ?? "",
    success_criteria: edit?.success_criteria ?? "",
    due_time: edit?.due_time ?? "",
    check_time: edit?.check_time ?? "",
    date: edit?.date ?? me.today,
    mode: "once" as "once" | "repeat",
    weekdays: 0b0011111,
    starts_on: me.today,
    ends_on: "",
  });
  const a = useAction();
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const submit = () =>
    a.run(async () => {
      const times = { due_time: f.due_time || null, check_time: f.check_time };
      const common = { text: f.text, success_criteria: f.success_criteria || null, ...times };
      if (edit) {
        await patch(`/assignments/${edit.id}`, { command_id: key, version: edit.version, date: f.date, ...common });
        navigate(`/a/${edit.id}`);
      } else if (f.mode === "once") {
        const r = await post<Assignment>("/assignments", { idempotency_key: key, child_id: f.child_id, date: f.date, ...common });
        navigate(`/a/${r.id}`);
      } else {
        await post("/recurrences", {
          idempotency_key: key,
          child_id: f.child_id,
          weekdays: f.weekdays,
          starts_on: f.starts_on,
          ends_on: f.ends_on || null,
          ...common,
        });
        navigate("/");
      }
    });
  return (
    <div className="screen">
      <Header title={edit ? "Изменить задание" : "Новое задание"} back />
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        {!edit && (
          <Field label="Кому" group>
            <Chips options={kids.map((c): [string, string] => [c.id, c.name])} value={f.child_id} onChange={(v) => setF({ ...f, child_id: v })} />
          </Field>
        )}
        <Field label="Что сделать (как сказали устно)">
          <textarea value={f.text} onChange={set("text")} required rows={3} />
        </Field>
        <Field label="Как поймём, что сделано (опц.)">
          <input value={f.success_criteria} onChange={set("success_criteria")} />
        </Field>
        <div className="row">
          <Field label="Срок (опц.)">
            <input type="time" value={f.due_time} onChange={set("due_time")} />
          </Field>
          <Field label="Проверка">
            <input type="time" value={f.check_time} onChange={set("check_time")} required />
          </Field>
        </div>
        {!edit && (
          <Field label="Повтор" group>
            <Chips
              options={[
                ["once", "Разово"],
                ["repeat", "По дням"],
              ]}
              value={f.mode}
              onChange={(v) => setF({ ...f, mode: v })}
            />
          </Field>
        )}
        {f.mode === "once" ? (
          <Field label="Дата">
            <input type="date" value={f.date} onChange={set("date")} required />
          </Field>
        ) : (
          <>
            <Field label="Дни недели" group>
              <div className="week">
                {WEEK.map(([bit, label]) => (
                  <button
                    type="button"
                    key={bit}
                    className={f.weekdays & (1 << bit) ? "on" : ""}
                    onClick={() => setF({ ...f, weekdays: f.weekdays ^ (1 << bit) })}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </Field>
            <div className="row">
              <Field label="С">
                <input type="date" value={f.starts_on} onChange={set("starts_on")} required />
              </Field>
              <Field label="По (опц.)">
                <input type="date" value={f.ends_on} onChange={set("ends_on")} />
              </Field>
            </div>
          </>
        )}
        <ErrorBox error={a.error} />
        <button className="primary" disabled={a.busy || (f.mode === "repeat" && !f.weekdays)}>
          {edit ? "Сохранить" : "Создать"}
        </button>
        <Note>Проверка не раньше срока. Если срок пустой — он равен времени проверки.</Note>
      </form>
    </div>
  );
}

export function AssignmentView({ id }: { id: string }) {
  const { data: a, error, reload, setData } = useLoad(() => get<Assignment>(`/assignments/${id}`), [id]);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [comment, setComment] = useState("");
  const [note, setNote] = useState("");
  const [correcting, setCorrecting] = useState(false);
  const [key, setKey] = useState(newKey);
  const act = useAction();
  if (!a) return <div className="screen"><Header title="Задание" back /><ErrorBox error={error} /></div>;

  const conflictReload = (e: unknown) => {
    reload();
    throw e;
  };
  const saveReview = () =>
    act.run(async () => {
      const r = await post<Assignment>(`/assignments/${a.id}/reviews`, {
        idempotency_key: key,
        outcome,
        comment: comment || null,
        supersedes_review_id: correcting ? a.current_review?.id : null,
      }).catch(conflictReload);
      setData(r);
      setOutcome(null);
      setComment("");
      setCorrecting(false);
      setKey(newKey());
    });
  const cancel = () =>
    act.run(async () => {
      if (!confirmCancel()) return;
      setData(await post<Assignment>(`/assignments/${a.id}/cancel`, { command_id: newKey(), version: a.version }).catch(conflictReload));
    });
  const addNote = () =>
    act.run(async () => {
      setData(await post<Assignment>(`/assignments/${a.id}/comments`, { text: note }));
      setNote("");
    });

  const title = a.state === "closed" ? "Задание (закрыто)" : a.state === "cancelled" ? "Задание (отменено)" : "Задание";
  return (
    <div className="screen">
      <Header title={title} back />
      <h2>{a.text}</h2>
      <p className="muted">
        {a.child_name} · дал: {a.created_by_name}
        {a.recurrence_text && ` · ↻ ${a.recurrence_text}`} · {dayTitle(a.date)}
      </p>
      {a.success_criteria && (
        <>
          <h3>Критерий</h3>
          <p>{a.success_criteria}</p>
        </>
      )}
      <div className="row muted">
        <span>Срок: {a.due_time}</span>
        <span>Проверка: {a.check_time}</span>
      </div>
      {a.child_marked_at && <Note>Ребёнок отметил «сделал» в {dateTimeOf(a.child_marked_at)}. Это не результат — результат ставит родитель.</Note>}
      {a.state === "cancelled" && <Note>Отменено: {a.cancelled_by_name}, {dateTimeOf(a.cancelled_at!)}. Запись остаётся в истории.</Note>}

      {a.current_review && (
        <>
          <h3>Текущий результат</h3>
          <div className="card static">
            <b>
              {OUTCOME[a.current_review.outcome].icon} {OUTCOME[a.current_review.outcome].text}
            </b>
            <div className="meta">
              {a.current_review.reviewer_name} · {dateTimeOf(a.current_review.reviewed_at)}
            </div>
          </div>
        </>
      )}

      {(a.state === "active" || correcting) && (
        <>
          <h3>{correcting ? "Новый результат" : "Результат"}</h3>
          <div className="outcomes">
            {(Object.keys(OUTCOME) as Outcome[]).map((o) => (
              <button key={o} type="button" className={outcome === o ? "on" : ""} onClick={() => setOutcome(o)}>
                {OUTCOME[o].icon}
                <br />
                {OUTCOME[o].text}
              </button>
            ))}
          </div>
          <Field label="Комментарий (опц.)">
            <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={2} placeholder="«Не поняла условие №4»" />
          </Field>
          <button className="primary" disabled={!outcome || act.busy} onClick={saveReview}>
            {correcting ? "Сохранить исправление" : "Сохранить проверку"}
          </button>
        </>
      )}
      {a.state === "closed" && !correcting && (
        <button className="secondary" onClick={() => setCorrecting(true)}>
          Исправить результат
        </button>
      )}
      <ErrorBox error={act.error} />

      {a.state === "active" && (
        <div className="row">
          <button className="secondary" onClick={() => navigate(`/a/${a.id}/edit`)}>
            Изменить
          </button>
          <button className="secondary" onClick={cancel} disabled={act.busy}>
            Отменить задание
          </button>
        </div>
      )}

      {a.reviews && a.reviews.length > 1 && (
        <>
          <h3>История проверок</h3>
          {a.reviews.map((r) => (
            <p key={r.id} className="muted">
              {dateTimeOf(r.reviewed_at)} {r.reviewer_name} — {r.corrects ? "исправил(а) на " : ""}«{OUTCOME[r.outcome].text}»
            </p>
          ))}
        </>
      )}

      <h3>Комментарии</h3>
      {a.comments?.map((c) => (
        <p key={c.id}>
          <span className="muted">
            {c.author_name}
            {c.by_child ? " (ребёнок)" : ""} · {timeOf(c.created_at)}:
          </span>{" "}
          {c.text}
        </p>
      ))}
      <div className="row">
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Заметка" />
        <button className="secondary small" disabled={!note.trim() || act.busy} onClick={addNote}>
          Добавить
        </button>
      </div>
      <Note>Одна кнопка — одна проверка. Двойной клик не создаёт вторую. Если второй родитель успел раньше — «Уже изменено, обновите».</Note>
    </div>
  );
}

function confirmCancel(): boolean {
  return window.confirm("Отменить задание? Оно останется в истории.");
}

export function AssignmentEdit({ me, id }: { me: Me; id: string }) {
  const { data, error } = useLoad(() => get<Assignment>(`/assignments/${id}`), [id]);
  if (!data) return <div className="screen"><ErrorBox error={error} /></div>;
  return <AssignmentForm me={me} edit={data} />;
}

type HistoryData = { summary: Record<string, number>; items: Assignment[] };

export function History({ me, unread, childMode = false }: { me: Me; unread: number; childMode?: boolean }) {
  const [child, setChild] = useState(me.children?.[0]?.id ?? "");
  const [period, setPeriod] = useState("week");
  const [outcome, setOutcome] = useState("all");
  const q = new URLSearchParams({ period, outcome, ...(child && !childMode ? { child_id: child } : {}) });
  const { data, error } = useLoad(() => get<HistoryData>(`/history?${q}`), [q.toString()]);
  const groups = new Map<string, Assignment[]>();
  for (const a of data?.items ?? []) groups.set(a.date, [...(groups.get(a.date) ?? []), a]);
  const s = data?.summary;
  return (
    <div className="screen">
      <Header title="История" right={childMode ? null : <Bell unread={unread} />} />
      {!childMode && (
        <Chips options={[...(me.children ?? []).map((c): [string, string] => [c.id, c.name]), ["", "Все"]]} value={child} onChange={setChild} />
      )}
      <div className="row">
        <select value={period} onChange={(e) => setPeriod(e.target.value)}>
          <option value="week">Неделя</option>
          <option value="month">Месяц</option>
          <option value="all">Всё время</option>
        </select>
        <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
          <option value="all">Все</option>
          <option value="done">Выполнено</option>
          <option value="partial">Частично</option>
          <option value="not_done">Не выполнено</option>
          <option value="cancelled">Отменено</option>
        </select>
      </div>
      <ErrorBox error={error} />
      {s && (
        <div className="card static">
          <b>
            ✓ {s.done} · ½ {s.partial} · ✗ {s.not_done} · отм. {s.cancelled}
          </b>
          <div className="meta">
            {s.marked_but_not_done > 0 && `Отметил «сделал», а проверка — «не выполнено»: ${s.marked_but_not_done}. `}
            Без оценок личности — только факты.
          </div>
        </div>
      )}
      {[...groups].map(([day, items]) => (
        <div key={day}>
          <h3>{dayTitle(day)}</h3>
          {items.map((a) => (
            <Card key={a.id} a={a} showChild={!child && !childMode} href={`#/a/${a.id}`} />
          ))}
        </div>
      ))}
      {data && data.items.length === 0 && <p className="muted">За период ничего нет.</p>}
    </div>
  );
}
