import { OperatorOperations } from "@/components/operator/OperatorOperations";
import { getServerSession } from "@/lib/session/server";

export default async function OperatorOperationDetailPage({
  params,
}: {
  readonly params: Promise<{ operation_id: string }>;
}) {
  const session = await getServerSession();
  if (session.status !== "authenticated") return null;
  const { operation_id: operationId } = await params;
  const organizations = session.memberships
    .filter((membership) => membership.organization_type === "OPERATOR")
    .map((membership) => ({
      id: membership.organization_id,
      role: membership.role,
    }));
  return (
    <OperatorOperations
      organizations={organizations}
      operationId={operationId}
    />
  );
}
