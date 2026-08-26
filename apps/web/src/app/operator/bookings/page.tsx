import { getServerSession } from "@/lib/session/server";
import { OperatorBookingQueue } from "@/components/operator/OperatorBookingQueue";

export default async function OperatorBookingsPage() {
  const session = await getServerSession();
  if (session.status !== "authenticated") return null;
  const organizations = session.memberships
    .filter((membership) => membership.organization_type === "OPERATOR")
    .map((membership) => ({
      id: membership.organization_id,
      role: membership.role,
      canDecide:
        membership.role === "OPERATOR_ADMIN" ||
        membership.role === "OPERATOR_OPERATIONS",
    }));
  return <OperatorBookingQueue organizations={organizations} />;
}
