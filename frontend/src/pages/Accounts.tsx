import { useState, type FormEvent } from "react";
import {
  logout,
  startAuth,
  verifyCode,
  verifyPassword,
  type AuthStep,
} from "../api/auth";
import { ApiError } from "../api/client";
import { PageHeader } from "../components/PageHeader";
import { useAuthStatus } from "../hooks/useAuthStatus";

type LoginStep = "credentials" | "code" | "password";

const SAVED_STEP_KEY = "telegram-manager.auth-step";
const SAVED_CHALLENGE_KEY = "telegram-manager.auth-challenge";

function savedStep(): LoginStep {
  const step = sessionStorage.getItem(SAVED_STEP_KEY);
  return step === "code" || step === "password" ? step : "credentials";
}

export default function Accounts() {
  const { status, refresh } = useAuthStatus();
  const [step, setStep] = useState<LoginStep>(savedStep);
  const [challengeId, setChallengeId] = useState(
    () => sessionStorage.getItem(SAVED_CHALLENGE_KEY) ?? "",
  );
  const [apiId, setApiId] = useState("");
  const [apiHash, setApiHash] = useState("");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rememberStep = (nextStep: LoginStep, nextChallenge = challengeId) => {
    setStep(nextStep);
    setChallengeId(nextChallenge);
    if (nextStep === "credentials") {
      sessionStorage.removeItem(SAVED_STEP_KEY);
      sessionStorage.removeItem(SAVED_CHALLENGE_KEY);
    } else {
      sessionStorage.setItem(SAVED_STEP_KEY, nextStep);
      sessionStorage.setItem(SAVED_CHALLENGE_KEY, nextChallenge);
    }
  };

  const handleError = (caught: unknown) => {
    if (caught instanceof ApiError) {
      setError(caught.message);
      if (["challenge_not_found", "challenge_expired", "code_expired"].includes(caught.code)) {
        rememberStep("credentials", "");
      }
    } else {
      setError("Не удалось связаться с backend.");
    }
  };

  const applyResult = async (result: AuthStep) => {
    if (result.next_step === "complete") {
      rememberStep("credentials", "");
      setApiHash("");
      setPassword("");
      await refresh();
      return;
    }
    rememberStep(result.next_step, result.challenge_id);
  };

  const handleStart = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await applyResult(await startAuth(Number(apiId), apiHash, phone));
    } catch (caught) {
      handleError(caught);
    } finally {
      setBusy(false);
    }
  };

  const handleCode = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await applyResult(await verifyCode(challengeId, code));
    } catch (caught) {
      handleError(caught);
    } finally {
      setBusy(false);
    }
  };

  const handlePassword = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await applyResult(await verifyPassword(challengeId, password));
    } catch (caught) {
      handleError(caught);
    } finally {
      setBusy(false);
    }
  };

  const handleLogout = async () => {
    setBusy(true);
    setError(null);
    try {
      await logout();
      rememberStep("credentials", "");
      await refresh();
    } catch (caught) {
      handleError(caught);
    } finally {
      setBusy(false);
    }
  };

  if (status.state === "loading") {
    return (
      <>
        <PageHeader title="Telegram-аккаунт" subtitle="Подключение локальной сессии" />
        <div className="card muted">Проверяю сохранённую сессию...</div>
      </>
    );
  }

  if (status.state === "ready" && status.data.authenticated && status.data.account) {
    const account = status.data.account;
    return (
      <>
        <PageHeader title="Telegram-аккаунт" subtitle="Подключение локальной сессии" />
        <div className="card auth-card">
          <div>
            <span className="pill ok">Подключён</span>
            <h3>{account.display_name}</h3>
            <p className="muted">
              {account.username ? `@${account.username}` : "Без username"} · ID {account.telegram_user_id}
            </p>
          </div>
          <button className="button secondary" type="button" disabled={busy} onClick={handleLogout}>
            Отключить
          </button>
        </div>
        <p className="muted small">
          Отключение завершает текущий клиент. Сохранённая сессия восстановится при следующем запуске.
        </p>
        {error && <div className="alert error">{error}</div>}
      </>
    );
  }

  return (
    <>
      <PageHeader title="Вход в Telegram" subtitle="Данные остаются на этом компьютере" />
      <div className="card auth-form-card">
        {step === "credentials" && (
          <form onSubmit={handleStart}>
            <h3>Параметры приложения</h3>
            <p className="muted small">
              Получите api_id и api_hash на my.telegram.org. Номер укажите в международном формате.
            </p>
            <div className="form-grid">
              <label className="field">
                <span>API ID</span>
                <input
                  inputMode="numeric"
                  value={apiId}
                  onChange={(event) => setApiId(event.target.value)}
                  required
                />
              </label>
              <label className="field">
                <span>API Hash</span>
                <input
                  type="password"
                  autoComplete="off"
                  value={apiHash}
                  onChange={(event) => setApiHash(event.target.value)}
                  required
                />
              </label>
              <label className="field full-width">
                <span>Телефон</span>
                <input
                  type="tel"
                  autoComplete="tel"
                  placeholder="+79990000000"
                  value={phone}
                  onChange={(event) => setPhone(event.target.value)}
                  required
                />
              </label>
            </div>
            <button className="button" type="submit" disabled={busy}>
              {busy ? "Подключаюсь..." : "Получить код"}
            </button>
          </form>
        )}

        {step === "code" && (
          <form onSubmit={handleCode}>
            <h3>Код подтверждения</h3>
            <p className="muted small">Введите код из сообщения Telegram.</p>
            <label className="field">
              <span>Код</span>
              <input
                inputMode="numeric"
                autoComplete="one-time-code"
                value={code}
                onChange={(event) => setCode(event.target.value)}
                required
                autoFocus
              />
            </label>
            <button className="button" type="submit" disabled={busy}>
              {busy ? "Проверяю..." : "Продолжить"}
            </button>
          </form>
        )}

        {step === "password" && (
          <form onSubmit={handlePassword}>
            <h3>Двухэтапная проверка</h3>
            <p className="muted small">Для аккаунта включён облачный пароль Telegram.</p>
            <label className="field">
              <span>Пароль</span>
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                autoFocus
              />
            </label>
            <button className="button" type="submit" disabled={busy}>
              {busy ? "Проверяю..." : "Войти"}
            </button>
          </form>
        )}
      </div>
      {error && <div className="alert error">{error}</div>}
      <p className="muted small">
        Сессия и API-реквизиты сохраняются в локальном каталоге data, исключённом из git.
      </p>
    </>
  );
}
