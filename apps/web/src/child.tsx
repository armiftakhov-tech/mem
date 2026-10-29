import { useState } from "react";
import { Assignment, Me, get, post } from "./api";
import { Card } from "./assignments";
import { ErrorBox, Field, Header, Note, OUTCOME, dayTitle, timeOf, useAction, useLoad } from "./ui";

export function ChildToday({ me }: { me: Me }) {
  const { data, error } = useLoad(() => get<Assignment[]>("/assignments/today"));
  const list = data ?? [];
  const todo = list.filter((a) => a.state === "active" && !a.child_marked_at);
  const marked = list.filter((a) => a.state === "active" && a.child_marked_at);
  const checked = list.filter((a) => a.state === "closed");
  return (
    <div className="screen">
      <Header title={`${me.child!.name}, ${dayTitle(me.today)}`} />
      <ErrorBox error={error} />
      {data && list.length === 0 && <p className="muted">На сегодня заданий нет.</p>}
      {[
        ["Сделать", todo],
        ["Отмечено, ждёт проверки", marked],
        ["Проверено", checked],
      ].map(([title, items]) =>
        (items as Assignment[]).length ? (
          <div key={title as string}>
            <h3>{title as string}</h3>
            {(items as Assignment[]).map((a) => (
              <Card key={a.id} a={a} showChild={false} href={`#/a/${a.id}`} />
            ))}
          </div>
        ) : null,
      )}
    </div>
  );
}

export function ChildAssignment({ id }: { id: string }) {
  const { data: a, error, setData } = useLoad(() => get<Assignment>(`/assignments/${id}`), [id]);
  const [comment, setComment] = useState("");
  const act = useAction();
  if (!a) return <div className="screen"><Header title="Задание" back /><ErrorBox error={error} /></div>;
  return (
    <div className="screen">
      <Header title="Задание" back />
      <h2>{a.text}</h2>
      <p className="muted">
        Дал(а): {a.created_by_name} · срок {a.due_time} · проверка {a.check_time}
      </p>
      {a.success_criteria && (
        <>
          <h3>Как поймём, что сделано</h3>
          <p>{a.success_criteria}</p>
        </>
      )}
      {a.current_review && (
        <div className="card static">
          <b>
            Проверено: {OUTCOME[a.current_review.outcome].icon} {OUTCOME[a.current_review.outcome].text}
          </b>
          <div className="meta">{a.current_review.reviewer_name}</div>
        </div>
      )}
      {a.state === "active" && !a.child_marked_at && (
        <>
          <Field label="Комментарий (опц.)">
            <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={2} />
          </Field>
          <button className="primary" disabled={act.busy} onClick={() => act.run(async () => setData(await post<Assignment>(`/assignments/${a.id}/mark`, { comment: comment || null })))}>
            Я сделал(а)
          </button>
          <Note>Отметка — не оценка. В {a.check_time} родитель проверит результат.</Note>
        </>
      )}
      {a.child_marked_at && a.state === "active" && <Note>Ты отметил(а) «сделал(а)». Ждёт проверки в {a.check_time}.</Note>}
      <ErrorBox error={act.error} />
      {!!a.comments?.length && <h3>Комментарии</h3>}
      {a.comments?.map((c) => (
        <p key={c.id}>
          <span className="muted">
            {c.author_name} · {timeOf(c.created_at)}:
          </span>{" "}
          {c.text}
        </p>
      ))}
    </div>
  );
}
