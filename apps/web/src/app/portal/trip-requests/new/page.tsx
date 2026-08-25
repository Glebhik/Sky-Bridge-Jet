import { NewTripRequestForm } from "@/components/portal/NewTripRequestForm";

/**
 * `/portal/trip-requests/new` — the customer create-a-trip-request page. It is protected by
 * the existing portal layout (authenticated shell + active-organization context); all of the
 * real journey logic lives in {@link NewTripRequestForm}.
 */
export default function NewTripRequestPage() {
  return <NewTripRequestForm />;
}
