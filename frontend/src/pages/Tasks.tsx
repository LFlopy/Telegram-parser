import { PageHeader, StubCard } from "../components/PageHeader";

export default function Tasks() {
  return (
    <>
      <PageHeader title="Задачи" subtitle="История сборов, статусы, отмена" />
      <StubCard text="Здесь будет список задач сбора, текущий прогресс (WebSocket), отмена и статусы: pending, running, waiting, completed, cancelled, failed." />
    </>
  );
}
