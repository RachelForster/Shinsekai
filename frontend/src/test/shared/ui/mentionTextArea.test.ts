import { describe, expect, it } from "vitest";

import {
  characterMentionOptions,
  filterMentionOptions,
  insertMention,
  mentionQueryAt,
  parseRecentMentionIds,
  rememberRecentMentionId,
  resolveMentionCaret,
  scrollChildIntoContainer,
  sortMentionOptions,
  splitMentionSegments,
} from "../../../shared/ui/mentionTokens";

const options = characterMentionOptions(
  [
    { color: "#66ccff", name: "Nanami" },
    { color: "#ff99aa", name: "Mika" },
  ],
  "User",
);

describe("mentionTextArea helpers", () => {
  it("includes the user plus unique character labels", () => {
    expect(options.map((option) => option.id)).toEqual(["user", "Nanami", "Mika"]);
  });

  it("detects an @ query after whitespace", () => {
    expect(mentionQueryAt("meet @Na", 8)).toEqual({ query: "Na", start: 5 });
    expect(mentionQueryAt("a@Na", 4)).toBeNull();
    expect(resolveMentionCaret("@", 0)).toBe(1);
  });

  it("inserts a mention token and splits it into a chip segment", () => {
    expect(insertMention("@", 0, options[1], 0)).toEqual({ caret: 8, value: "@Nanami " });
    const next = insertMention("meet @Na", 8, options[1], 5);
    expect(next).toEqual({ caret: 13, value: "meet @Nanami " });
    expect(splitMentionSegments(next.value, options)).toEqual([
      { type: "text", value: "meet " },
      { option: options[1], type: "mention", value: "@Nanami" },
      { type: "text", value: " " },
    ]);
  });

  it("filters mention options by label", () => {
    expect(filterMentionOptions(options, "mika").map((option) => option.label)).toEqual(["Mika"]);
  });

  it("sorts mention options by most recently used ids", () => {
    expect(parseRecentMentionIds('["Mika","user"]')).toEqual(["Mika", "user"]);
    expect(rememberRecentMentionId(["user", "Nanami"], "Mika")).toEqual(["Mika", "user", "Nanami"]);
    expect(sortMentionOptions(options, ["Mika"]).map((option) => option.id)).toEqual(["Mika", "user", "Nanami"]);
  });

  it("scrolls a child into the container when it crosses the visible edge", () => {
    const container = { clientHeight: 80, scrollTop: 0 };
    scrollChildIntoContainer(container, { offsetHeight: 36, offsetTop: 200 });
    expect(container.scrollTop).toBe(156);
    scrollChildIntoContainer(container, { offsetHeight: 36, offsetTop: 0 });
    expect(container.scrollTop).toBe(0);
  });
});
