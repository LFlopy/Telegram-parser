import { useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../api/client";
import {
  checkGroupAccess,
  fetchGroups,
  resolveGroup,
  type TelegramGroup,
} from "../api/groups";
import { PageHeader } from "../components/PageHeader";

const PAGE_SIZE = 20;
const SELECTED_GROUP_KEY = "telegram-manager.selected-group";

function savedGroup(): TelegramGroup | null {
  const value = localStorage.getItem(SELECTED_GROUP_KEY);
  if (!value) return null;
  try {
    const group = JSON.parse(value) as TelegramGroup;
    return typeof group.id === "number" && typeof group.title === "string" ? group : null;
  } catch {
    return null;
  }
}

export default function Groups() {
  const [groups, setGroups] = useState<TelegramGroup[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [publicAddress, setPublicAddress] = useState("");
  const [selected, setSelected] = useState<TelegramGroup | null>(savedGroup);
  const [loading, setLoading] = useState(true);
  const [checkingId, setCheckingId] = useState<number | null>(null);
  const [resolving, setResolving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    void fetchGroups(search, page, PAGE_SIZE)
      .then((result) => {
        if (!active) return;
        setGroups(result.items);
        setTotal(result.total);
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setError(
          caught instanceof ApiError ? caught.message : "Не удалось загрузить список групп.",
        );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [search, page]);

  const updateAccessState = (
    groupId: number,
    accessState: TelegramGroup["access_state"],
  ) => {
    setGroups((current) =>
      current.map((group) =>
        group.id === groupId ? { ...group, access_state: accessState } : group,
      ),
    );
  };

  const selectGroup = async (group: TelegramGroup) => {
    setCheckingId(group.id);
    setError(null);
    setNotice(null);
    try {
      const access = await checkGroupAccess(group.id);
      if (!access.can_read_members) {
        updateAccessState(group.id, "no_access");
        setNotice(access.reason ?? "Список участников этой группы недоступен.");
        return;
      }
      const availableGroup = { ...group, access_state: "available" as const };
      updateAccessState(group.id, "available");
      setSelected(availableGroup);
      localStorage.setItem(SELECTED_GROUP_KEY, JSON.stringify(availableGroup));
      setNotice(`Выбрана группа «${group.title}».`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Не удалось проверить доступ.");
    } finally {
      setCheckingId(null);
    }
  };

  const applySearch = (event: FormEvent) => {
    event.preventDefault();
    setPage(1);
    setSearch(searchInput);
  };

  const handleResolve = async (event: FormEvent) => {
    event.preventDefault();
    setResolving(true);
    setError(null);
    setNotice(null);
    try {
      const group = await resolveGroup(publicAddress);
      setGroups((current) => [group, ...current.filter((item) => item.id !== group.id)]);
      setNotice(`Группа «${group.title}» найдена. Проверьте доступ перед выбором.`);
      setPublicAddress("");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Не удалось найти группу.");
    } finally {
      setResolving(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <>
      <PageHeader title="Группы" subtitle="Доступные диалоги и выбор источника" />

      {selected && (
        <div className="card selected-group">
          <div>
            <span className="pill ok">Источник выбран</span>
            <h3>{selected.title}</h3>
            <p className="muted small">
              {selected.username ? `@${selected.username} · ` : ""}ID {selected.telegram_group_id}
            </p>
          </div>
        </div>
      )}

      <div className="card group-controls">
        <form className="inline-form" onSubmit={applySearch}>
          <label className="field grow">
            <span>Поиск по диалогам</span>
            <input
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="Название или username"
            />
          </label>
          <button className="button" type="submit">Найти</button>
        </form>

        <form className="inline-form" onSubmit={handleResolve}>
          <label className="field grow">
            <span>Публичная группа</span>
            <input
              value={publicAddress}
              onChange={(event) => setPublicAddress(event.target.value)}
              placeholder="@username или https://t.me/username"
              required
            />
          </label>
          <button className="button secondary" type="submit" disabled={resolving}>
            {resolving ? "Проверяю..." : "Открыть"}
          </button>
        </form>
      </div>

      {error && <div className="alert error">{error}</div>}
      {notice && <div className="alert notice">{notice}</div>}

      <div className="card table-card">
        {loading ? (
          <p className="muted">Загружаю группы...</p>
        ) : groups.length === 0 ? (
          <p className="muted">Подходящие группы не найдены.</p>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Название</th>
                  <th>Тип</th>
                  <th>Доступ</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {groups.map((group) => (
                  <tr key={group.id}>
                    <td>
                      <strong>{group.title}</strong>
                      <div className="muted small">
                        {group.username ? `@${group.username}` : `ID ${group.telegram_group_id}`}
                      </div>
                    </td>
                    <td>{group.group_type === "supergroup" ? "Супергруппа" : "Группа"}</td>
                    <td>
                      <span
                        className={
                          group.access_state === "available"
                            ? "pill ok"
                            : group.access_state === "no_access"
                              ? "pill bad"
                              : "pill"
                        }
                      >
                        {group.access_state === "available"
                          ? "Доступна"
                          : group.access_state === "no_access"
                            ? "Нет доступа"
                            : "Не проверена"}
                      </span>
                    </td>
                    <td className="table-action">
                      <button
                        className="button secondary"
                        type="button"
                        disabled={checkingId !== null}
                        onClick={() => void selectGroup(group)}
                      >
                        {checkingId === group.id ? "Проверяю..." : "Выбрать"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

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
    </>
  );
}
