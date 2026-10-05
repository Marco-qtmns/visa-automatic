import { CaseDetailClient } from "@/components/CaseDetailClient";

export default async function CaseDetailPage({ params }: { params: Promise<{ caseId: string }> }) {
  const { caseId } = await params;
  return <CaseDetailClient caseId={caseId} />;
}
