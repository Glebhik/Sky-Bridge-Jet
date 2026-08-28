import { PlatformComplianceDetail } from "@/components/platform/PlatformComplianceDetail";

export default async function AuthorizationDetail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  return (
    <PlatformComplianceDetail
      kind="aircraft-authorizations"
      id={(await params).id}
    />
  );
}
