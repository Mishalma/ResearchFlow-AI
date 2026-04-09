export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  return Response.json(
    { error: "The generic backend tunnel has been retired." },
    { status: 404 },
  );
}

export async function POST() {
  return Response.json(
    { error: "The generic backend tunnel has been retired." },
    { status: 404 },
  );
}
