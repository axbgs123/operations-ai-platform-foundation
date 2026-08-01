import { beforeEach, expect, test } from "vitest";
import {
  clearExperiencePreferences,
  readExperiencePreferences,
  writeCopyMode,
  writePageGuidance,
} from "./experience-preferences";

beforeEach(() => localStorage.clear());

test("defaults to simple copy with guidance on", () => {
  expect(readExperiencePreferences(localStorage, "member-1")).toEqual({
    copyMode: "simple",
    pageGuidance: "on",
  });
});

test("stores the two preferences independently per member", () => {
  writeCopyMode(localStorage, "member-1", "professional");
  writePageGuidance(localStorage, "member-1", "off");
  writeCopyMode(localStorage, "member-2", "simple");

  expect(readExperiencePreferences(localStorage, "member-1")).toEqual({
    copyMode: "professional",
    pageGuidance: "off",
  });
  expect(readExperiencePreferences(localStorage, "member-2")).toEqual({
    copyMode: "simple",
    pageGuidance: "on",
  });
});

test("rejects invalid stored values without copying them to another member", () => {
  localStorage.setItem("operations-ai:copy-mode:member-1", "PRIVATE_DATA");
  localStorage.setItem("operations-ai:page-guidance:member-1", "sometimes");
  expect(readExperiencePreferences(localStorage, "member-1")).toEqual({
    copyMode: "simple",
    pageGuidance: "on",
  });
});

test("clears only experience preference keys", () => {
  localStorage.setItem("operations-ai:copy-mode:member-1", "professional");
  localStorage.setItem("operations-ai:page-guidance:member-1", "off");
  localStorage.setItem("operations-ai:sidebar:member-1", "collapsed");
  localStorage.setItem("unrelated", "keep");
  clearExperiencePreferences(localStorage);
  expect(localStorage.getItem("operations-ai:copy-mode:member-1")).toBeNull();
  expect(localStorage.getItem("operations-ai:page-guidance:member-1")).toBeNull();
  expect(localStorage.getItem("operations-ai:sidebar:member-1")).toBe("collapsed");
  expect(localStorage.getItem("unrelated")).toBe("keep");
});
