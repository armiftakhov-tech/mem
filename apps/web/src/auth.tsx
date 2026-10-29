import { useState } from "react";
import { post } from "./api";
import { Chips, ErrorBox, Field, Header, Note, RELATIONS, navigate, useAction } from "./ui";

const TIMEZONES = [
  "Europe/Kaliningrad",
  "Europe/Moscow",
  "Europe/Samara",
  "Asia/Yekaterinburg",
  "Asia/Omsk",
  "Asia/Novosibirsk",
  "Asia/Krasnoyarsk",
  "Asia/Irkutsk",
  "Asia/Yakutsk",
  "Asia/Vladivostok",
  "Asia/Magadan",
  "Asia/Kamchatka",
];

export function Setup({ onDone }: { onDone: () => void }) {
  const [f, setF] = useState({ token: "", email: "", password: "", name: "", timezone: "Europe/Moscow", relation_type: "father", child: "", birth: "" });
  const a = useAction();
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const zones = TIMEZONES.includes(browserTz) ? TIMEZONES : [browserTz, ...TIMEZONES];
  return (
    <div className="screen">
      <Header title="Настройка семьи" />
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          a.run(async () => {
            await post("/auth/setup", {
              token: f.token,
              email: f.email,
              password: f.password,
              name: f.name,
              timezone: f.timezone,
              relation_type: f.relation_type,
              child: { name: f.child, birth_date: f.birth || null },
            });
            onDone();
          });
        }}
      >
        <p className="muted">Один раз. Токен — в логе сервера: строка BOOTSTRAP TOKEN.</p>
        <Field label="Bootstrap-токен (из консоли админа)">
          <input value={f.token} onChange={set("token")} required autoComplete="off" />
        </Field>
        <Field label="Email (логин)">
          <input type="email" value={f.email} onChange={set("email")} required autoComplete="username" />
        </Field>
        <Field label="Пароль (от 8 символов)">
          <input type="password" value={f.password} onChange={set("password")} required minLength={8} autoComplete="new-password" />
        </Field>
        <Field label="Ваше имя">
          <input value={f.name} onChange={set("name")} required />
        </Field>
        <Field label="Часовой пояс семьи">
          <select value={f.timezone} onChange={set("timezone")}>
            {zones.map((z) => (
              <option key={z}>{z}</option>
            ))}
          </select>
        </Field>
        <h3>Первый ребёнок</h3>
        <div className="row">
          <Field label="Имя">
            <input value={f.child} onChange={set("child")} required />
          </Field>
          <Field label="Дата рожд. (опц.)">
            <input type="date" value={f.birth} onChange={set("birth")} />
          </Field>
        </div>
        <Field label="Кто вы для ребёнка" group>
          <Chips options={RELATIONS} value={f.relation_type} onChange={(v) => setF({ ...f, relation_type: v })} />
        </Field>
        <ErrorBox error={a.error} />
        <button className="primary" disabled={a.busy}>
          Создать семью
        </button>
        <Note>После создания токен сгорает. Открытой регистрации нет.</Note>
      </form>
    </div>
  );
}

export function Login({ onDone }: { onDone: () => void }) {
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const a = useAction();
  return (
    <div className="screen">
      <Header title="Дисциплина" />
      <form
        className="form login"
        onSubmit={(e) => {
          e.preventDefault();
          a.run(async () => {
            await post("/auth/login", { login, password });
            onDone();
          });
        }}
      >
        <Field label="Логин (email родителя или имя ребёнка)">
          <input value={login} onChange={(e) => setLogin(e.target.value)} required autoComplete="username" autoCapitalize="off" />
        </Field>
        <Field label="Пароль">
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" />
        </Field>
        <ErrorBox error={a.error} />
        <button className="primary" disabled={a.busy}>
          Войти
        </button>
        <Note>Кнопки «Забыли пароль» нет. Родителю пароль сбрасывает администратор командой на сервере, ребёнку — родитель в профиле ребёнка.</Note>
        <Note>
          Есть код приглашения? <a href="#/join">Вступить в семью</a>
        </Note>
      </form>
    </div>
  );
}

export function Join({ onDone }: { onDone: () => void }) {
  const [f, setF] = useState({ code: "", email: "", password: "", name: "", relation_type: "mother" });
  const a = useAction();
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <div className="screen">
      <Header title="Вход по приглашению" back="/" />
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          a.run(async () => {
            await post("/auth/accept-invitation", f);
            navigate("/");
            onDone();
          });
        }}
      >
        <Field label="Код приглашения">
          <input value={f.code} onChange={set("code")} required placeholder="K7QM-2XPA" autoCapitalize="characters" />
        </Field>
        <Field label="Email">
          <input type="email" value={f.email} onChange={set("email")} required autoComplete="username" />
        </Field>
        <Field label="Пароль (от 8 символов)">
          <input type="password" value={f.password} onChange={set("password")} required minLength={8} autoComplete="new-password" />
        </Field>
        <Field label="Ваше имя">
          <input value={f.name} onChange={set("name")} required />
        </Field>
        <Field label="Кто вы для детей" group>
          <Chips options={RELATIONS} value={f.relation_type} onChange={(v) => setF({ ...f, relation_type: v })} />
        </Field>
        <ErrorBox error={a.error} />
        <button className="primary" disabled={a.busy}>
          Вступить в семью
        </button>
        <Note>Уже есть аккаунт без семьи? Введите его email и пароль. Права те же, что у первого родителя.</Note>
      </form>
    </div>
  );
}
