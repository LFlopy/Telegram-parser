import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import type { TelegramGroup } from "../api/groups";
import {
  cancelTask,
  fetchTasks,
  startParse,
  taskEventsUrl,
  type ParseTask,
  type TaskStatus,
} from "../api/tasks";
import { PageHeader } from "../components/PageHeader";

const SELECTED_GROUP_KEY = "telegram-manager.selected-group";
const ACTIVE_STATUSES: TaskStatus[] = ["pending", "running", "waiting"];

const STATUS_LABELS: Record<TaskStatus, string> = {
  pending: "В очереди",
  running: "Сбор",
  waiting: "Ожидание Telegram",
  completed: "Завершена",
  cancelled: "Отменена",
  failed: "Ошибка",
};

function selectedGroup(): TelegramGroup | null {
  const raw = localStorage.getItem(SELECTED_GROUP_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as TelegramGroup;
  } catch {
    return null;
  }
}

function statusClass(status: TaskStatus): string {
  if (status === "completed") return "pill ok";
  if (status === "failed" || status === "cancelled") return "pill bad";
  if (status === "waiting") return "pill warn";
  return "pill";
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(new Date(value));
}

export default function Tasks() {
  const [group] = useState<TelegramGroup | null>(selectedGroup);
  const [tasks, setTasks] = useState<ParseTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [cancelling, setCancelling] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const mergeTask = useCallback((task: ParseTask) => {
    setTasks((current) => [task, ...current.filter((item) => item.id !== task.id)]);
  }, []);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const page = await fetchTasks();
      setTasks(page.items);
      setError(null);
    } catch (caught) {
      if (!quiet) {
        setError(caught instanceof ApiError ? caught.message : "Не удалось загрузить задачи.");
      }
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const poll = window.setInterval(() => void load(true), 5000);
    let socket: WebSocket | null = null;
    let reconnect: number | null = null;
    let stopped = false;

    const connect = () => {
      socket = new WebSocket(taskEventsUrl());
      socket.onmessage = (event) => {
        try {
          mergeTask(JSON.parse(event.data as string) as ParseTask);
        } catch {
          // A later polling pass restores the authoritative state.
        }
      };
      socket.onclose = () => {
        if (!stopped) reconnect = window.setTimeout(connect, 1500);
      };
    };
    connect();
    return () => {
      stopped = true;
      window.clearInterval(poll);
      if (reconnect !== null) window.clearTimeout(reconnect);
      socket?.close();
    };
  }, [load, mergeTask]);

  const active = tasks.find((task) => ACTIVE_STATUSES.includes(task.status));

  const start = async () => {
    if (!group) return;
    setStarting(true);
    setError(null);
    try {
      mergeTask(await startParse(group.id));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Не удалось запустить сбор.");
    } finally {
      setStarting(false);
    }
  };

  const cancel = async (task: ParseTask) => {
    setCancelling(task.id);
    setError(null);
    try {
      mergeTask(await cancelTask(task.id));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Не удалось отменить задачу.");
    } finally {
      setCancelling(null);
    }
  };

  return (
    <>
      <PageHeader title="Задачи" subtitle="История сборов, статусы, отмена" />

      <div className="card task-launcher">
        <div>
          <h3>{group ? group.title : "Источник не выбран"}</h3>
          <p className="muted small">
            {group
              ? "Участники сохраняются пакетами; повторный сбор не создаёт дублей."
              : "Выберите доступную группу в разделе «Группы»."}
          </p>
        </div>
        <button
          className="button"
          type="button"
          disabled={!group || starting || Boolean(active)}
          onClick={() => void start()}
        >
          {starting ? "Запускаю..." : active ? "Сбор уже выполняется" : "Начать сбор"}
        </button>
      </div>

      {error && <div className="alert error">{error}</div>}

      {active && (
        <div className="card task-progress">
          <div className="task-progress-title">
            <div>
              <span className={statusClass(active.status)}>{STATUS_LABELS[active.status]}</span>
              <h3>{active.group_title}</h3>
            </div>
            <button
              className="button secondary"
              type="button"
              disabled={cancelling === active.id}
              onClick={() => void cancel(active)}
            >
              {cancelling === active.id ? "Отменяю..." : "Отменить"}
            </button>
          </div>
          <div className="counter-grid">
            <div><strong>{active.processed_count}</strong><span>Обработано</span></div>
            <div><strong>{active.saved_count}</strong><span>Сохранено</span></div>
            <div><strong>{active.skipped_count}</strong><span>Повторы</span></div>
            <div><strong>{active.error_count}</strong><span>Ошибки</span></div>
          </div>
          {active.error_message && <p className="muted small">{active.error_message}</p>}
        </div>
      )}

      <div className="card table-card">
        {loading ? (
          <p className="muted">Загружаю историю...</p>
        ) : tasks.length === 0 ? (
          <p className="muted">Сборы ещё не запускались.</p>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Группа</th>
                  <th>Статус</th>
                  <th>Сохранено</th>
                  <th>Запущена</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => (
                  <tr key={task.id}>
                    <td>
                      <strong>{task.group_title}</strong>
                      {task.error_message && <div className="task-error small">{task.error_message}</div>}
                    </td>
                    <td><span className={statusClass(task.status)}>{STATUS_LABELS[task.status]}</span></td>
                    <td>{task.saved_count} / {task.processed_count}</td>
                    <td>{formatDate(task.created_at)}</td>
                    <td className="table-action">
                      {ACTIVE_STATUSES.includes(task.status) ? (
                        <button
                          className="button secondary"
                          type="button"
                          disabled={cancelling === task.id}
                          onClick={() => void cancel(task)}
                        >
                          Отменить
                        </button>
                      ) : (
                        <Link className="button secondary result-link" to={`/members?task=${task.id}`}>
                          Результат
                        </Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
