import EditorClientPage from "./editor-client";

type EditorPageSearchParams = Promise<{
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

export default async function EditorPage({
  searchParams,
}: {
  searchParams: EditorPageSearchParams;
}) {
  const resolvedSearchParams = await searchParams;
  const projectId = getSingleSearchParam(resolvedSearchParams.projectId);
  const title = getSingleSearchParam(resolvedSearchParams.title);

  return <EditorClientPage projectId={projectId} title={title} />;
}
