import { OperatorBookingHistory } from "@/components/operator/OperatorBookingHistory";
import { getServerSession } from "@/lib/session/server";

export default async function OperatorBookingHistoryPage() {
  const session = await getServerSession();
  if (session.status !== "authenticated") return null;
  const organizations = session.memberships
    .filter((membership) => membership.organization_type === "OPERATOR")
    .map((membership) => ({
      id: membership.organization_id,
      role: membership.role,
    }));
  return <OperatorBookingHistory organizations={organizations} />;
}
