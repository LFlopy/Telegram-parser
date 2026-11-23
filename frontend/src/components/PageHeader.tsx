type Props = { title: string; subtitle?: string; children?: React.ReactNode };

export function PageHeader({ title, subtitle, children }: Props) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
      </div>
      {children}
    </header>
  );
}

export function StubCard({ text }: { text: string }) {
  return (
    <div className="card stub">
      <div className="stub-badge">Раздел в разработке</div>
      <p>{text}</p>
      <p className="muted small">Раздел станет доступен в одном из следующих обновлений.</p>
    </div>
  );
}
