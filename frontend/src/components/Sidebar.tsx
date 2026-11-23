import { NavLink } from "react-router-dom";
import { useHealth } from "../hooks/useHealth";

const MENU = [
  { to: "/", label: "Главная", icon: "🏠" },
  { to: "/accounts", label: "Аккаунты", icon: "👤" },
  { to: "/groups", label: "Группы", icon: "👥" },
  { to: "/members", label: "Участники", icon: "🗂️" },
  { to: "/tasks", label: "Задачи", icon: "⚙️" },
  { to: "/settings", label: "Настройки", icon: "🔧" },
];

export function Sidebar() {
  const health = useHealth();
  const dotClass =
    health.state === "online" ? "dot online" : health.state === "offline" ? "dot offline" : "dot loading";
  const dotText =
    health.state === "online"
      ? "Backend: работает"
      : health.state === "offline"
        ? "Backend: недоступен"
        : "Backend: проверка...";

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <span className="brand-icon">✈️</span>
        <div>
          <div className="brand-title">Telegram Manager</div>
          <div className="brand-sub">локальная панель</div>
        </div>
      </div>

      <nav className="sidebar-nav">
        {MENU.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) => (isActive ? "nav-item active" : "nav-item")}
          >
            <span className="nav-icon">{item.icon}</span>
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-footer">
        <span className={dotClass} />
        <span>{dotText}</span>
      </div>
    </aside>
  );
}
