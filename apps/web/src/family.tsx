import { useState } from "react";
import { del, get, newKey, patch, post, put } from "./api";
import { Bell } from "./assignments";
import { Chips, ErrorBox, Field, Header, Note, RELATIONS, dateTimeOf, navigate, useAction, useLoad } from "./ui";

type ChildRow = { id: string; name: string; birth_date: string | null; age: number | null; today_count: number; to_check_count: number; can_delete: boolean; login: string | null };
type Rec = { id: string; child_id: string; text: string; weekdays_text: string; due_time: string; check_time: string; status: "active" | "paused"; version: number };

const REC_STATUS = { active: "активен", paused: "пауза" };

export function Children({ unread, onChange }: { unread: number; onChange: () => void }) {
  const kids = useLoad(() => get<ChildRow[]>("/children"));
  const recs = useLoad(() => get<Rec[]>("/recurrences"));
  const [open, setOpen] = useState<string | null>(null);
  const act = useAction();
  const setStatus = (r: Rec, status: string) =>
    act.run(async () => {
      if (status === "ended" && !window.confirm("Завершить повтор? Уже созданные задания останутся.")) return;
      await patch(`/recurrences/${r.id}`, { command_id: newKey(), version: r.version, status });
      setOpen(null);
      recs.reload();
      onChange();
    });
  return (
    <div className="screen">
      <Header title="Дети" right={<Bell unread={unread} />} />
      <ErrorBox error={kids.error ?? act.error} />
      {kids.data?.map((c) => (
        <div key={c.id}>
          <a className="card" href={`#/children/${c.id}`}>
            <b>
              {c.name}
              {c.age !== null && `, ${c.age}`}
            </b>
            <div className="meta">
              Сегодня: {c.today_count} · к проверке {c.to_check_count} · {c.login ? `вход: ${c.login}` : "без входа"}
            </div>
          </a>
          {recs.data?.some((r) => r.child_id === c.id) && <h3>Повторы: {c.name}</h3>}
          {recs.data
            ?.filter((r) => r.child_id === c.id)
            .map((r) => (
              <div key={r.id}>
                <button className="card" onClick={() => setOpen(open === r.id ? null : r.id)}>
                  <b>{r.text}</b>
                  <div className="meta">
                    {r.weekdays_text} · {r.due_time} / {r.check_time} <span className="badge">{REC_STATUS[r.status]}</span>
                  </div>
                </button>
                {open === r.id && (
                  <div className="row">
                    {r.status === "active" ? (
                      <button className="secondary small" onClick={() => setStatus(r, "paused")}>Пауза</button>
                    ) : (
                      <button className="secondary small" onClick={() => setStatus(r, "active")}>Возобновить</button>
                    )}
                    <button className="secondary small" onClick={() => setStatus(r, "ended")}>Завершить</button>
                  </div>
                )}
              </div>
            ))}
          <hr />
        </div>
      ))}
      <button className="secondary" onClick={() => navigate("/children/new")}>
        + Добавить ребёнка
      </button>
      <Note>Тап по повтору: пауза / завершить. Уже созданные задания не меняются.</Note>
    </div>
  );
}

export function ChildForm({ id, onChange }: { id?: string; onChange: () => void }) {
  const { data: kids } = useLoad(() => (id ? get<ChildRow[]>("/children") : Promise.resolve([])), [id]);
  const existing = kids?.find((c) => c.id === id);
  const [f, setF] = useState<{ name: string; birth_date: string; relation_type: string } | null>(id ? null : { name: "", birth_date: "", relation_type: "father" });
  const [acc, setAcc] = useState({ login: "", password: "" });
  const act = useAction();
  const accAct = useAction();
  const [accDone, setAccDone] = useState("");
  if (id && existing && !f) setF({ name: existing.name, birth_date: existing.birth_date ?? "", relation_type: "father" });
  if (!f) return <div className="screen"><Header title="Ребёнок" back="/children" /></div>;
  const set = (k: "name" | "birth_date") => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const save = () =>
    act.run(async () => {
      const body = { ...f, birth_date: f.birth_date || null };
      if (id) await patch(`/children/${id}`, body);
      else await post("/children", body);
      onChange();
      navigate("/children");
    });
  const remove = () =>
    act.run(async () => {
      if (!window.confirm("Удалить ребёнка? Это нельзя отменить.")) return;
      await del(`/children/${id}`);
      onChange();
      navigate("/children");
    });
  const saveAccount = () =>
    accAct.run(async () => {
      await put(`/children/${id}/account`, acc);
      setAccDone(`Готово. Логин: ${acc.login.trim().toLowerCase()}. Пароль передайте ребёнку.`);
      setAcc({ login: "", password: "" });
    });
  return (
    <div className="screen">
      <Header title={id ? f.name || "Ребёнок" : "Новый ребёнок"} back="/children" />
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          save();
        }}
      >
        <Field label="Имя">
          <input value={f.name} onChange={set("name")} required />
        </Field>
        <Field label="Дата рождения (опц.)">
          <input type="date" value={f.birth_date} onChange={set("birth_date")} />
        </Field>
        <Field label="Кто вы для ребёнка" group>
          <Chips options={RELATIONS} value={f.relation_type} onChange={(v) => setF({ ...f, relation_type: v })} />
        </Field>
        <ErrorBox error={act.error} />
        <button className="primary" disabled={act.busy}>
          Сохранить
        </button>
        <Note>Все родители семьи связываются с ребёнком автоматически.</Note>
      </form>
      {id && (
        <>
          <hr />
          <h3>Вход ребёнка</h3>
          <p className="muted">
            {existing?.login ? `Сейчас: ${existing.login}. Новый логин или пароль выкинет ребёнка из всех сессий.` : "Входа нет. Ребёнок увидит только свои задания и сможет отметить «сделал»."}
          </p>
          <div className="row">
            <input placeholder="логин, напр. masha" value={acc.login} onChange={(e) => setAcc({ ...acc, login: e.target.value })} autoCapitalize="off" />
            <input placeholder="пароль, от 6" type="text" value={acc.password} onChange={(e) => setAcc({ ...acc, password: e.target.value })} />
          </div>
          <ErrorBox error={accAct.error} />
          {accDone && <Note>{accDone}</Note>}
          <button className="secondary" disabled={accAct.busy || acc.login.length < 2 || acc.password.length < 6} onClick={saveAccount}>
            {existing?.login ? "Сменить логин и пароль" : "Создать вход"}
          </button>
          {existing?.can_delete && (
            <>
              <hr />
              <button className="secondary" onClick={remove} disabled={act.busy}>
                Удалить ребёнка
              </button>
              <p className="muted">Кнопка есть, пока у ребёнка нет ни одного задания и повтора.</p>
            </>
          )}
        </>
      )}
    </div>
  );
}

type Notif = { id: string; type: string; text: string; assignment_id: string | null; created_at: string; read: boolean };

export function Notifications({ onChange }: { onChange: () => void }) {
  const { data, reload } = useLoad(() => get<{ items: Notif[] }>("/notifications"));
  const open = async (n: Notif) => {
    if (!n.read) await post(`/notifications/${n.id}/read`);
    onChange();
    if (n.assignment_id) navigate(`/a/${n.assignment_id}`);
    else reload();
  };
  return (
    <div className="screen">
      <Header
        title="Уведомления"
        back
        right={
          <button
            className="link"
            onClick={async () => {
              await post("/notifications/read-all");
              reload();
              onChange();
            }}
          >
            прочитать все
          </button>
        }
      />
      {data?.items.map((n) => (
        <button key={n.id} className={`card ${n.read ? "" : "unread"}`} onClick={() => open(n)}>
          <b>{n.text}</b>
          <div className="meta">
            {dateTimeOf(n.created_at)}
            {n.read && " · прочитано"}
          </div>
        </button>
      ))}
      {data && data.items.length === 0 && <p className="muted">Пусто.</p>}
      <Note>Только внутри приложения. Закрытое приложение на телефоне не разбудим.</Note>
    </div>
  );
}

type Settings = { reminders_enabled: boolean; changes_enabled: boolean; browser_notifications_enabled: boolean };

export function More({ onLogout }: { onLogout: () => void }) {
  const parents = useLoad(() => get<{ id: string; name: string }[]>("/parents"));
  const st = useLoad(() => get<Settings>("/settings/notifications"));
  const [pw, setPw] = useState({ old_password: "", new_password: "" });
  const [pwOpen, setPwOpen] = useState(false);
  const act = useAction();
  const toggle = (k: keyof Settings) =>
    act.run(async () => {
      const next = { ...st.data!, [k]: !st.data![k] };
      if (k === "browser_notifications_enabled" && next[k] && "Notification" in window) await Notification.requestPermission();
      st.setData(await put<Settings>("/settings/notifications", next));
    });
  const perm = "Notification" in window ? Notification.permission : "unsupported";
  return (
    <div className="screen">
      <Header title="Ещё" />
      <a className="card" href="#/invite">
        Пригласить второго родителя ›
      </a>
      <div className="card static">Родители семьи: {parents.data?.map((p) => p.name).join(", ")}</div>
      <h3>Уведомления (только мои)</h3>
      {st.data && (
        <div className="toggles">
          <label>
            <input type="checkbox" checked={st.data.reminders_enabled} onChange={() => toggle("reminders_enabled")} /> Напоминать о проверке
          </label>
          <label>
            <input type="checkbox" checked={st.data.changes_enabled} onChange={() => toggle("changes_enabled")} /> Изменения от другого родителя и ребёнка
          </label>
          <label>
            <input type="checkbox" checked={st.data.browser_notifications_enabled} onChange={() => toggle("browser_notifications_enabled")} /> Уведомления браузера
          </label>
          <p className="muted">
            Браузер: {perm === "granted" ? "разрешение выдано" : perm === "denied" ? "запрещено" : perm === "unsupported" ? "не поддерживает" : "разрешение не выдано"}
          </p>
        </div>
      )}
      <hr />
      <button className="card" onClick={() => setPwOpen(!pwOpen)}>
        Сменить пароль ›
      </button>
      {pwOpen && (
        <form
          className="form"
          onSubmit={(e) => {
            e.preventDefault();
            act.run(async () => {
              await post("/auth/password", pw);
              setPw({ old_password: "", new_password: "" });
              setPwOpen(false);
            });
          }}
        >
          <input type="password" placeholder="Старый пароль" value={pw.old_password} onChange={(e) => setPw({ ...pw, old_password: e.target.value })} required />
          <input type="password" placeholder="Новый пароль, от 8" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} minLength={8} required />
          <button className="primary" disabled={act.busy}>Сменить</button>
        </form>
      )}
      <ErrorBox error={act.error} />
      <button className="card" onClick={onLogout}>
        Выйти
      </button>
    </div>
  );
}

type Inv = { id: string; hint: string; created_by_name: string; expires_at: string; status: string; code?: string };
const INV_STATUS: Record<string, string> = { pending: "ожидает", accepted: "принято", revoked: "отозвано", expired: "истекло" };

export function Invite() {
  const list = useLoad(() => get<Inv[]>("/invitations"));
  const [fresh, setFresh] = useState<Inv | null>(null);
  const act = useAction();
  return (
    <div className="screen">
      <Header title="Приглашение" back="/more" />
      <p className="muted">Второй родитель открывает это приложение по тому же адресу и вводит код на экране входа.</p>
      {fresh && (
        <>
          <div className="code">{fresh.code}</div>
          <p className="muted center">Действует до {dateTimeOf(fresh.expires_at)} · одноразовый. Больше код не покажем.</p>
          <div className="row">
            <button className="secondary" onClick={() => navigator.clipboard?.writeText(fresh.code!)}>
              Скопировать
            </button>
            <button
              className="secondary"
              onClick={() =>
                act.run(async () => {
                  await post(`/invitations/${fresh.id}/revoke`);
                  setFresh(null);
                  list.reload();
                })
              }
            >
              Отозвать
            </button>
          </div>
        </>
      )}
      <h3>Приглашения</h3>
      {list.data?.map((i) => (
        <div key={i.id} className="card static">
          <b>{i.hint}</b>
          <div className="meta">
            создал {i.created_by_name} · {INV_STATUS[i.status]}
          </div>
        </div>
      ))}
      <ErrorBox error={act.error} />
      <button
        className="primary"
        disabled={act.busy}
        onClick={() =>
          act.run(async () => {
            setFresh(await post<Inv>("/invitations"));
            list.reload();
          })
        }
      >
        Новый код
      </button>
      <Note>Передать код вручную. Писем приложение не шлёт.</Note>
    </div>
  );
}
