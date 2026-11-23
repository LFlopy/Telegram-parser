import { PageHeader, StubCard } from "../components/PageHeader";
import { useHealth } from "../hooks/useHealth";

export default function Settings() {
  const health = useHealth();
  return (
    <>
      <PageHeader title="Настройки" subtitle="Сведения о приложении и локальные параметры" />
      <div className="card">
        <h3>Приложение</h3>
        <table className="kv">
          <tbody>
            <tr>
              <td>Имя</td>
              <td>{health.body?.name ?? "—"}</td>
            </tr>
            <tr>
              <td>Версия</td>
              <td>{health.body?.version ?? "—"}</td>
            </tr>
            <tr>
              <td>Backend</td>
              <td>
                {health.state === "online"
                  ? "доступен"
                  : health.state === "offline"
                    ? "недоступен"
                    : "проверка..."}
              </td>
            </tr>
            <tr>
              <td>Режим</td>
              <td>локальный (127.0.0.1)</td>
            </tr>
          </tbody>
        </table>
      </div>
      <StubCard text="Здесь появятся путь к данным, безопасное отключение аккаунта и управление сессией." />
    </>
  );
}
