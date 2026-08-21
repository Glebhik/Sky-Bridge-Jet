import { Badge, Card, PageHeading } from "@/components/ui/primitives";
import { demoFixtures } from "@/lib/demo/fixtures";

export default function DemoAccountPage() {
  return (
    <>
      <PageHeading
        title="Account"
        description="Synthetic account presentation. No account action is available."
      />
      <Card>
        <h2 className="card__title">Demonstration customer</h2>
        <dl className="detail-list">
          <div>
            <dt>Name</dt>
            <dd>{demoFixtures.customer.name}</dd>
          </div>
          <div>
            <dt>Organization</dt>
            <dd>{demoFixtures.customer.organization}</dd>
          </div>
          <div>
            <dt>Access</dt>
            <dd>
              <Badge tone="info">{demoFixtures.customer.accessLabel}</Badge>
            </dd>
          </div>
        </dl>
      </Card>
      <Card>
        <h2 className="card__title">Account actions</h2>
        <p>
          Editing, password changes, recovery, invitations, and sign-out are not
          available in this demonstration.
        </p>
      </Card>
    </>
  );
}
