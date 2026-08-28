import { OperatorAircraftInventory } from "@/components/operator/OperatorAircraftInventory";
import { getServerSession } from "@/lib/session/server";
export default async function Page() {
  const session = await getServerSession();
  if (session.status !== "authenticated") return null;
  const organizations = session.memberships
    .filter((m) => m.organization_type === "OPERATOR")
    .map((m) => ({
      id: m.organization_id,
      role: m.role,
      canCreate: m.role === "OPERATOR_ADMIN",
    }));
  return <OperatorAircraftInventory organizations={organizations} />;
}
