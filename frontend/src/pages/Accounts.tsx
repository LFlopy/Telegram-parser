import { PageHeader, StubCard } from "../components/PageHeader";

export default function Accounts() {
  return (
    <>
      <PageHeader title="Аккаунты" subtitle="Подключённые Telegram-аккаунты" />
      <StubCard text="Здесь будет статус аккаунта, авторизация (api_id, api_hash, телефон, код, 2FA) и повторное подключение из сохранённой сессии." />
    </>
  );
}
