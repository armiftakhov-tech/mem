import { useEffect, useState } from "react";

type Health = { status: "ok"; revision: string } | { status: "not_ready"; reason: string };

// Этап 0: только проверка, что связка Caddy → API → SQLite жива. Экраны — с этапа 1.
export function App() {
  const [health, setHealth] = useState<Health | "offline" | null>(null);

  useEffect(() => {
    fetch("/api/health/ready")
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setHealth("offline"));
  }, []);

  let text = "Проверяю сервер…";
  if (health === "offline") text = "Нет связи с сервером";
  else if (health?.status === "ok") text = `Сервер готов, схема БД ${health.revision}`;
  else if (health) text = `Сервер не готов: ${health.reason}`;

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: 16, maxWidth: 480, margin: "0 auto" }}>
      <h1>Дисциплина</h1>
      <p>{text}</p>
    </main>
  );
}
