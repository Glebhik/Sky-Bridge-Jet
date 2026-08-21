import { demoFixtures } from "@/lib/demo/fixtures";

export default function DemoAccountPage() {
  const customer = demoFixtures.customer;

  return (
    <>
      <header className="sbj-page-head">
        <p className="sbj-kicker">Account</p>
        <h1>Account</h1>
        <p>Synthetic account presentation. No account action is available.</p>
      </header>
      <div className="sbj-stack">
        <section className="sbj-panel">
          <h2 className="sbj-stat">Demonstration customer</h2>
          <dl className="sbj-dl">
            <div>
              <dt>Name</dt>
              <dd>{customer.name}</dd>
            </div>
            <div>
              <dt>Organization</dt>
              <dd>{customer.organization}</dd>
            </div>
            <div>
              <dt>Contact</dt>
              <dd>{customer.contact}</dd>
            </div>
            <div>
              <dt>Access</dt>
              <dd>{customer.accessLabel}</dd>
            </div>
          </dl>
        </section>
        <section className="sbj-panel">
          <h2 className="sbj-stat">Travel preferences</h2>
          <p>{customer.travelPreferences}</p>
        </section>
        <section className="sbj-panel">
          <h2 className="sbj-stat">Communication preferences</h2>
          <p>{customer.communicationPreferences}</p>
        </section>
        <section className="sbj-panel">
          <h2 className="sbj-stat">Security</h2>
          <p>{customer.securitySummary}</p>
          <p className="sbj-activity__detail">
            Editing, password changes, recovery, invitations, and sign-out are
            not available in this demonstration.
          </p>
        </section>
      </div>
    </>
  );
}
