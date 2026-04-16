type SectionHeadingProps = {
  eyebrow?: string;
  title: string;
  description?: string;
  align?: "left" | "center";
};

export function SectionHeading({
  eyebrow,
  title,
  description,
  align = "center",
}: SectionHeadingProps) {
  const isCentered = align === "center";

  return (
    <div
      className={`space-y-4 ${
        isCentered ? "mx-auto max-w-3xl text-center" : "max-w-2xl"
      }`}
    >
      {eyebrow ? (
        <p className="text-xs font-semibold uppercase tracking-[0.28em] text-indigo-300/80">
          {eyebrow}
        </p>
      ) : null}
      <h2 className="text-3xl font-bold tracking-tight text-white md:text-4xl">
        {title}
      </h2>
      {description ? (
        <p className="text-base leading-7 text-indigo-200/72 md:text-lg">
          {description}
        </p>
      ) : null}
    </div>
  );
}
