export function StatusMark({
  status,
  tone,
}: {
  status: string;
  tone: "warning" | "success" | "neutral";
}) {
  return (
    <span className={`sbj-status sbj-status--${tone}`}>
      <span className="sbj-status__mark" aria-hidden="true" />
      {status}
    </span>
  );
}
