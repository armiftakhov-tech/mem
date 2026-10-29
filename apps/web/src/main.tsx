import { StrictMode, useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { ApiError, Me, get, post } from "./api";
import { AssignmentEdit, AssignmentForm, AssignmentView, History, Today } from "./assignments";
import { Join, Login, Setup } from "./auth";
import { ChildAssignment, ChildToday } from "./child";
import { ChildForm, Children, Invite, More, Notifications } from "./family";
import "./styles.css";
import { navigate, useHash } from "./ui";

type State = { kind: "loading" } | { kind: "offline" } | { kind: "setup" } | { kind: "anon" } | { kind: "in"; me: Me };

function App() {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [unread, setUnread] = useState(0);
  const hash = useHash();

  const refresh = useCallback(async () => {
    try {
      setState({ kind: "in", me: await get<Me>("/me") });
    } catch (e) {
      if ((e as ApiError).status === 0) return setState({ kind: "offline" });
      const s = await get<{ setup_required: boolean }>("/auth/state").catch(() => null);
      setState(s === null ? { kind: "offline" } : s.setup_required ? { kind: "setup" } : { kind: "anon" });
    }
  }, []);
  useEffect(() => {
    refresh();
  }, [refresh]);

  const isParent = state.kind === "in" && state.me.kind === "parent";
  const pollUnread = useCallback(async () => {
    if (!isParent) return;
    try {
      const { unread: n } = await get<{ unread: number }>("/notifications/unread");
      setUnread((prev) => {
        if (n > prev && document.hidden && "Notification" in window && Notification.permission === "granted") {
          new Notification("Дисциплина", { body: `Новых уведомлений: ${n}` });
        }
        return n;
      });
    } catch (e) {
      if ((e as ApiError).status === 401) refresh();
    }
  }, [isParent, refresh]);
  useEffect(() => {
    pollUnread();
    const t = setInterval(pollUnread, 30000);
    return () => clearInterval(t);
  }, [pollUnread, hash]);

  useEffect(() => {
    const on = () => refresh();
    addEventListener("online", on);
    return () => removeEventListener("online", on);
  }, [refresh]);

  if (state.kind === "loading") return <div className="screen muted">Загрузка…</div>;
  if (state.kind === "offline")
    return (
      <div className="screen">
        <h1>Нет связи с сервером</h1>
        <p className="muted">Проверьте, что сервер запущен и вы в домашней сети или VPN.</p>
        <button className="primary" onClick={refresh}>
          Повторить
        </button>
      </div>
    );
  if (state.kind === "setup") return <Setup onDone={refresh} />;
  if (state.kind === "anon") return hash === "/join" ? <Join onDone={refresh} /> : <Login onDone={refresh} />;

  const me = state.me;
  const logout = async () => {
    await post("/auth/logout");
    navigate("/");
    refresh();
  };
  const [, section, id, sub] = hash.split("/");

  if (me.kind === "child") {
    const tabs: [string, string][] = [
      ["", "Сегодня"],
      ["history", "История"],
    ];
    let page;
    if (section === "a" && id) page = <ChildAssignment id={id} />;
    else if (section === "history") page = <History me={me} unread={0} childMode />;
    else page = <ChildToday me={me} />;
    return (
      <Shell tabs={tabs} section={section} extra={<button className="link" onClick={logout}>Выйти</button>}>
        {page}
      </Shell>
    );
  }

  let page;
  if (section === "new") page = <AssignmentForm me={me} />;
  else if (section === "a" && id && sub === "edit") page = <AssignmentEdit me={me} id={id} />;
  else if (section === "a" && id) page = <AssignmentView id={id} />;
  else if (section === "children" && id === "new") page = <ChildForm onChange={refresh} />;
  else if (section === "children" && id) page = <ChildForm id={id} onChange={refresh} />;
  else if (section === "children") page = <Children unread={unread} onChange={refresh} />;
  else if (section === "history") page = <History me={me} unread={unread} />;
  else if (section === "notifications") page = <Notifications onChange={pollUnread} />;
  else if (section === "more") page = <More onLogout={logout} />;
  else if (section === "invite") page = <Invite />;
  else page = <Today me={me} unread={unread} />;
  return (
    <Shell
      tabs={[
        ["", "Сегодня"],
        ["children", "Дети"],
        ["history", "История"],
        ["more", "Ещё"],
      ]}
      section={section}
    >
      {page}
    </Shell>
  );
}

function Shell({ tabs, section, children, extra }: { tabs: [string, string][]; section: string; children: React.ReactNode; extra?: React.ReactNode }) {
  const active = tabs.some(([t]) => t === section) ? section : "";
  return (
    <>
      <main>{children}</main>
      <nav className="tabs">
        {tabs.map(([t, label]) => (
          <a key={t} href={`#/${t}`} className={t === active ? "on" : ""}>
            {label}
          </a>
        ))}
        {extra}
      </nav>
    </>
  );
}

if ("serviceWorker" in navigator && location.protocol === "https:") {
  navigator.serviceWorker.register("/sw.js").catch(() => undefined);
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
