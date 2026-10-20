import { notFound } from "next/navigation";
import { HoldingDetail } from "@/components/portfolio/holding-detail";

export default async function HoldingPage({
  params,
}: {
  params: Promise<{ id: string; ticker: string }>;
}) {
  const { id, ticker } = await params;
  const portfolioId = Number(id);
  if (!Number.isSafeInteger(portfolioId) || portfolioId <= 0 || !ticker.trim())
    notFound();
  return <HoldingDetail portfolioId={portfolioId} ticker={ticker.toUpperCase()} />;
}
