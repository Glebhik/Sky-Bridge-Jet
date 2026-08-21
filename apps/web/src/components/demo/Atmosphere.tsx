/** Decorative, non-interactive atmosphere. Hidden from assistive technology. */
export function Atmosphere() {
  return (
    <div className="sbj-demo__atmosphere" aria-hidden="true">
      <svg className="sbj-demo__stars" viewBox="0 0 1200 800" focusable="false">
        <g fill="#e2c98f">
          <circle cx="80" cy="60" r="1.1" opacity="0.55" />
          <circle cx="220" cy="140" r="0.8" opacity="0.35" />
          <circle cx="410" cy="40" r="1.2" opacity="0.45" />
          <circle cx="640" cy="90" r="0.7" opacity="0.3" />
          <circle cx="890" cy="50" r="1" opacity="0.5" />
          <circle cx="1080" cy="130" r="0.9" opacity="0.4" />
          <circle cx="180" cy="320" r="0.7" opacity="0.25" />
          <circle cx="960" cy="280" r="1.1" opacity="0.35" />
        </g>
      </svg>
    </div>
  );
}

export function RouteArc() {
  return (
    <svg
      className="sbj-route-arc"
      viewBox="0 0 120 40"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M8 28 C 40 4, 80 4, 112 28"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
      />
      <circle cx="8" cy="28" r="2.4" fill="currentColor" />
      <circle cx="112" cy="28" r="2.4" fill="currentColor" />
    </svg>
  );
}

export function AbstractCraft() {
  return (
    <svg
      className="sbj-silhouette"
      viewBox="0 0 72 32"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M4 18 L34 16 L68 14 L58 18 L68 22 L34 20 L4 18 Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
      />
      <path
        d="M34 16 L38 8"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
      />
    </svg>
  );
}
