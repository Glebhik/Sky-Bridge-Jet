import { getApiBaseUrl } from "@/lib/env";

export default function Home() {
  return (
    <main className="hero">
      <p className="eyebrow">Phase 1</p>
      <h1>Sky Bridge Jet</h1>
      <p className="positioning">Premium Private Aviation Marketplace</p>
      <p className="summary">
        The web and API foundation is in place for the future Sky Bridge Jet
        experience.
      </p>
      <p className="api-status" data-api-base-url={getApiBaseUrl()}>
        API foundation configured
      </p>
    </main>
  );
}
