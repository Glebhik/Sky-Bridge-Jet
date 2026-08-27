import { OperatorBookingHistory } from "@/components/operator/OperatorBookingHistory";
import { getServerSession } from "@/lib/session/server";

export default async function OperatorBookingDetailPage({
  params,
}: {
  readonly params: Promise<{ booking_id: string }>;
}) {
  const session = await getServerSession();
  if (session.status !== "authenticated") return null;
  const { booking_id: bookingId } = await params;
  const organizations = session.memberships
    .filter((membership) => membership.organization_type === "OPERATOR")
    .map((membership) => ({
      id: membership.organization_id,
      role: membership.role,
    }));
  return (
    <OperatorBookingHistory
      organizations={organizations}
      bookingId={bookingId}
    />
  );
}
