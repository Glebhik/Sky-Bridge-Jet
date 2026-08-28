import { OperatorAircraftDetail } from "@/components/operator/OperatorAircraftDetail";
import { getServerSession } from "@/lib/session/server";
export default async function Page({
  params,
}: {
  params: Promise<{ aircraft_id: string }>;
}) {
  const session = await getServerSession();
  if (session.status !== "authenticated") return null;
  const organizations = session.memberships
    .filter((m) => m.organization_type === "OPERATOR")
    .map((m) => ({ id: m.organization_id, role: m.role }));
  return (
    <OperatorAircraftDetail
      aircraftId={(await params).aircraft_id}
      organizations={organizations}
    />
  );
}
