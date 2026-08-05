import type { ReactElement } from "react";


export function NavigationIcon({ name }: { name: string }): ReactElement {
  const paths: Record<string, string> = {
    home: "M8 11.5 12 8l4 3.5V16H8v-4.5Z",
    operations: "M7.5 8h9M7.5 12h9M7.5 16h6",
    creation: "m12 6 .9 3.1L16 10l-3.1.9L12 14l-.9-3.1L8 10l3.1-.9L12 6Z",
    assets: "M8 9.5 12 7l4 2.5v5L12 17l-4-2.5v-5Z",
    management: "M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z",
    agent: "M9 9h6M8 13h8M10 17h4M12 4v2",
  };
  return (
    <svg
      aria-hidden="true"
      className="h-5 w-5 shrink-0"
      fill="none"
      viewBox="0 0 24 24"
    >
      <rect
        height="16"
        rx="4"
        stroke="currentColor"
        strokeWidth="1.6"
        width="16"
        x="4"
        y="4"
      />
      <path
        d={paths[name] ?? (name.length % 2 === 0 ? "M8 12h8M12 8v8" : "M8 9h8M8 15h5")}
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.6"
      />
    </svg>
  );
}
