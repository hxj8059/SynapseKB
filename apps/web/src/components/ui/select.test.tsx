import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { MultiSelect, Select } from "./select";

const options = [
  { value: "source_time", label: "source_time" },
  { value: "created_at", label: "created_at" },
];

function SelectHarness() {
  const [value, setValue] = useState("source_time");
  return (
    <Select
      ariaLabel="时间字段"
      value={value}
      onValueChange={setValue}
      options={options}
    />
  );
}

function MultiSelectHarness() {
  const [value, setValue] = useState<string[]>(["source_time"]);
  return (
    <MultiSelect
      ariaLabel="字段范围"
      value={value}
      onValueChange={setValue}
      options={options}
    />
  );
}

describe("Select", () => {
  it("changes a single value from the custom menu", async () => {
    const user = userEvent.setup();
    render(<SelectHarness />);

    await user.click(screen.getByRole("button", { name: "时间字段" }));
    await user.click(screen.getByRole("menuitemradio", { name: "created_at" }));

    expect(screen.getByRole("button", { name: "时间字段" })).toHaveTextContent(
      "created_at",
    );
  });

  it("keeps the multi-select menu open while toggling options", async () => {
    const user = userEvent.setup();
    render(<MultiSelectHarness />);

    await user.click(screen.getByRole("button", { name: "字段范围" }));
    await user.click(screen.getByRole("menuitemcheckbox", { name: "created_at" }));

    expect(screen.getByText("已选择 2 项")).toBeInTheDocument();
    expect(screen.getByRole("menuitemcheckbox", { name: "created_at" })).toHaveAttribute(
      "data-state",
      "checked",
    );
  });
});
