import ProcessingClientPage from "./processing-client";

type ProcessingPageSearchParams = Promise<{
  projectId?: string | string[];
  title?: string | string[];
}>;

function getSingleSearchParam(
  value: string | string[] | undefined,
): string | null {
  if (Array.isArray(value)) {
    return value[0] ?? null;
  }

  return value ?? null;
}

export default async function ProcessingPage({
  searchParams,
}: {
  searchParams: ProcessingPageSearchParams;
}) {
  const resolvedSearchParams = await searchParams;
  const projectId = getSingleSearchParam(resolvedSearchParams.projectId);
  const title = getSingleSearchParam(resolvedSearchParams.title);

  return <ProcessingClientPage projectId={projectId} title={title} />;
}
