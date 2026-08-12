import { beforeEach, describe, expect, it, vi } from "vitest";

import Home from "./page";

const redirect = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({ redirect }));

describe("Home", () => {
  beforeEach(() => {
    redirect.mockReset();
  });

  it("routes the product root through the recoverable workspace entry", () => {
    Home();

    expect(redirect).toHaveBeenCalledOnce();
    expect(redirect).toHaveBeenCalledWith("/enter");
  });
});
