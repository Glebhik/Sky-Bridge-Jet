import { PlatformComplianceDetail } from "@/components/platform/PlatformComplianceDetail";

export default async function AdmissionDetail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  return <PlatformComplianceDetail kind="admissions" id={(await params).id} />;
}
