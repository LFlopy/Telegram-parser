import { PageHeader, StubCard } from "../components/PageHeader";

export default function Members() {
  return (
    <>
      <PageHeader title="Участники" subtitle="Собранные участники и результаты" />
      <StubCard text="Здесь будет таблица участников с серверной пагинацией и поиском." />
    </>
  );
}
