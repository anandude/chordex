import { STATIC_JOB_ID } from "@/lib/staticJob";
import ResultsClient from "./ResultsClient";

// One placeholder page for static export (Cloudflare Pages); other ids still
// render on demand under `next dev` and on Vercel.
export function generateStaticParams() {
  return [{ jobId: STATIC_JOB_ID }];
}

export default async function ResultsPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = await params;
  return <ResultsClient jobId={jobId} />;
}
