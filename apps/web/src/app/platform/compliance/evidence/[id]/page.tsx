import { PlatformComplianceDetail } from "@/components/platform/PlatformComplianceDetail";

export default async function EvidenceDetail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  return <PlatformComplianceDetail kind="evidence" id={(await params).id} />;
}
