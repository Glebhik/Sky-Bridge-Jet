import { PlatformPilotGovernance } from "@/components/platform/PlatformPilotGovernance";
import { getServerSession } from "@/lib/session/server";

export default async function PlatformPilotPage() {
  const session = await getServerSession();
  const canManage =
    session.status === "authenticated" &&
    session.permissions.includes("pilot.manage");
  return <PlatformPilotGovernance canManage={canManage} />;
}
