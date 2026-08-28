import { notFound } from "next/navigation";

import { PlatformPaymentDetail } from "@/components/platform/PlatformPaymentDetail";
import { getServerSession } from "@/lib/session/server";

const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export default async function PlatformPaymentPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  const session = await getServerSession();
  return (
    <PlatformPaymentDetail
      id={id}
      canOperate={
        session.status === "authenticated" &&
        session.permissions.includes("payment.operate")
      }
    />
  );
}
