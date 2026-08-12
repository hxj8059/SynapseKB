import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { DateTimePicker, displayValue, toLocalDateTime } from "./date-time-picker";

function Harness() {
  const [value, setValue] = useState("2026-08-06T09:30");
  return (
    <DateTimePicker
      ariaLabel="开始时间"
      value={value}
      onValueChange={setValue}
    />
  );
}

describe("DateTimePicker", () => {
  it("formats local values without converting timezones", () => {
    expect(displayValue("2026-08-06T09:30")).toBe("2026/08/06 09:30");
    expect(toLocalDateTime(new Date(2026, 7, 8), "14:05")).toBe(
      "2026-08-08T14:05",
    );
  });

  it("selects a calendar day and preserves the time", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "开始时间" }));
    await user.click(screen.getByRole("menuitem", { name: "2026-08-08" }));

    expect(screen.getByText("2026/08/08 09:30")).toBeInTheDocument();
  });
});
