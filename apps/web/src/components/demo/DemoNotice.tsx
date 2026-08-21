import { DEMO_NOTICE_POINTS } from "@/lib/demo/copy";
import { DEMO_DATA_BANNER } from "@/lib/demo/fixtures";

export function DemoNotice() {
  return (
    <aside className="sbj-notice" role="status">
      <p className="sbj-notice__title">{DEMO_DATA_BANNER}</p>
      <ul className="sbj-notice__list">
        {DEMO_NOTICE_POINTS.map((point) => (
          <li key={point}>{point}</li>
        ))}
      </ul>
    </aside>
  );
}
