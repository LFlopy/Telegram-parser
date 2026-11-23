import { PageHeader } from "../components/PageHeader";
import { useHealth } from "../hooks/useHealth";

export default function Home() {
  const health = useHealth();
  const healthText =
    health.state === "online"
      ? `Работает (версия ${health.body?.version ?? "?"})`
      : health.state === "offline"
        ? "Недоступен — проверьте, запущен ли backend"
        : "Проверяю...";

  return (
    <>
      <PageHeader title="Главная" subtitle="Состояние приложения и быстрый обзор" />

      <div className="card grid-2">
        <div>
          <h3>Backend</h3>
          <p>
            <span
              className={
                health.state === "online"
                  ? "pill ok"
                  : health.state === "offline"
                    ? "pill bad"
                    : "pill"
              }
            >
              {healthText}
            </span>
          </p>
          <p className="muted small">Проверка выполняется через GET /api/health</p>
        </div>
        <div>
          <h3>Telegram-аккаунт</h3>
          <p>
            <span className="pill">Не авторизован</span>
          </p>
          <p className="muted small">Подключение аккаунта пока недоступно.</p>
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <h3>Последний сбор</h3>
          <p className="muted">Задач ещё не выполнялось.</p>
        </div>
        <div className="card">
          <h3>Быстрый запуск</h3>
          <p className="muted">Станет доступен после подключения аккаунта.</p>
        </div>
      </div>
    </>
  );
}
