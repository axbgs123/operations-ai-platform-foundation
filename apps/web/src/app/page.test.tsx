import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Home from "./page";

describe("Home", () => {
  it("identifies the product and the mock experience", () => {
    render(<Home />);

    expect(
      screen.getByRole("heading", {
        name: "运营内容智能分析与生成平台",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Mock 模式")).toBeInTheDocument();
  });
});
