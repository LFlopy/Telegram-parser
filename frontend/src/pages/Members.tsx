import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { fetchTaskMembers, taskExportUrl, type Member } from "../api/members";
import { fetchTasks, type ParseTask } from "../api/tasks";
import { PageHeader } from "../components/PageHeader";

const PAGE_SIZE = 50;

function displayName(member: Member): string {
  const name = [member.first_name, member.last_name].filter(Boolean).join(" ");
  return name || member.username || `ID ${member.telegram_user_id}`;
}

export default function Members() {
  const [params, setParams] = useSearchParams();
  const taskId = params.get("task") ?? "";
  const [tasks, setTasks] = useState<ParseTask[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void fetchTasks(1, 100)
      .then((result) => {
        if (!active) return;
        setTasks(result.items);
        if (!taskId && result.items.length > 0) {
          const preferred = result.items.find((task) => task.status === "completed") ?? result.items[0];
          setParams({ task: preferred.id }, { replace: true });
        }
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(caught instanceof ApiError ? caught.message : "Не удалось загрузить задачи.");
        }
      });
    return () => {
      active = false;
    };
  }, [setParams, taskId]);

  useEffect(() => {
    if (!taskId) {
      setMembers([]);
      setTotal(0);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    void fetchTaskMembers(taskId, search, page, PAGE_SIZE)
      .then((result) => {
        if (!active) return;
        setMembers(result.items);
        setTotal(result.total);
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(caught instanceof ApiError ? caught.message : "Не удалось загрузить участников.");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [taskId, search, page]);

  const selectedTask = useMemo(
    () => tasks.find((task) => task.id === taskId) ?? null,
    [tasks, taskId],
  );
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const chooseTask = (value: string) => {
    setPage(1);
    setSearch("");
    setSearchInput("");
    setParams(value ? { task: value } : {}, { replace: true });
  };

  const applySearch = (event: FormEvent) => {
    event.preventDefault();
    setPage(1);
    setSearch(searchInput);
  };

  return (
    <>
      <PageHeader title="Участники" subtitle="Собранные участники и результаты" />

      <div className="card member-controls">
        <label className="field">
          <span>Результат сбора</span>
          <select value={taskId} onChange={(event) => chooseTask(event.target.value)}>
            <option value="">Выберите задачу</option>
            {tasks.map((task) => (
              <option key={task.id} value={task.id}>
                {task.group_title} · {task.saved_count} участников · {new Date(task.created_at).toLocaleString("ru-RU")}
              </option>
            ))}
          </select>
        </label>

        <form className="inline-form" onSubmit={applySearch}>
          <label className="field grow">
            <span>Поиск</span>
            <input
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="Имя, фамилия или username"
              disabled={!taskId}
            />
          </label>
          <button className="button secondary" type="submit" disabled={!taskId}>Найти</button>
        </form>

        {taskId && (
          <a className="button export-button" href={taskExportUrl(taskId)} download>
            Скачать CSV
          </a>
        )}
      </div>

      {selectedTask && (
        <p className="muted small result-summary">
          «{selectedTask.group_title}»: найдено {total} участников
        </p>
      )}
      {error && <div className="alert error">{error}</div>}

      <div className="card table-card">
        {loading ? (
          <p className="muted">Загружаю участников...</p>
        ) : !taskId ? (
          <p className="muted">Выберите завершённую задачу сбора.</p>
        ) : members.length === 0 ? (
          <p className="muted">
            {search ? "По вашему запросу ничего не найдено." : "В этой задаче нет сохранённых участников."}
          </p>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Участник</th>
                  <th>Username</th>
                  <th>Telegram ID</th>
                  <th>Тип</th>
                </tr>
              </thead>
              <tbody>
                {members.map((member) => (
                  <tr key={member.telegram_user_id}>
                    <td><strong>{displayName(member)}</strong></td>
                    <td>{member.username ? `@${member.username}` : <span className="muted">—</span>}</td>
                    <td>{member.telegram_user_id}</td>
                    <td>{member.is_bot ? <span className="pill warn">Бот</span> : "Пользователь"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {taskId && totalPages > 1 && (
        <div className="pagination">
          <button
            className="button secondary"
            type="button"
            disabled={page <= 1 || loading}
            onClick={() => setPage((current) => current - 1)}
          >
            Назад
          </button>
          <span className="muted small">Страница {page} из {totalPages}</span>
          <button
            className="button secondary"
            type="button"
            disabled={page >= totalPages || loading}
            onClick={() => setPage((current) => current + 1)}
          >
            Далее
          </button>
        </div>
      )}
    </>
  );
}
