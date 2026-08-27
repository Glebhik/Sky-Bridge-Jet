import { OperatorOpportunityMarketplace } from "@/components/operator/OperatorOpportunityMarketplace";
import { getServerSession } from "@/lib/session/server";

export default async function OperatorOpportunitiesPage() {
  const session = await getServerSession();
  if (session.status !== "authenticated") return null;
  const organizations = session.memberships
    .filter((membership) => membership.organization_type === "OPERATOR")
    .map((membership) => ({
      id: membership.organization_id,
      role: membership.role,
      canManage:
        membership.role === "OPERATOR_ADMIN" ||
        membership.role === "OPERATOR_SALES",
    }));
  return <OperatorOpportunityMarketplace organizations={organizations} />;
}
