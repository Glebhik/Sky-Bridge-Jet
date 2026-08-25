import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AirportPicker } from "@/components/portal/AirportPicker";
import type { Airport } from "@/lib/api/types";

const A1 = "11111111-1111-4111-8111-111111111111";
const A2 = "22222222-2222-4222-8222-222222222222";

const AIRPORTS: readonly Airport[] = [
  {
    id: A1,
    icao_code: "EIDW",
    iata_code: "DUB",
    name: "Dublin",
    city: "Dublin",
    country_code: "IE",
  },
  {
    id: A2,
    icao_code: "EGLL",
    iata_code: "LHR",
    name: "Heathrow",
    city: "London",
    country_code: "GB",
  },
];

function Harness({ onChange }: { onChange: (id: string | null) => void }) {
  const [value, setValue] = useState<string | null>(null);
  return (
    <AirportPicker
      id="pick"
      label="From"
      airports={AIRPORTS}
      value={value}
      onChange={(id) => {
        setValue(id);
        onChange(id);
      }}
    />
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AirportPicker", () => {
  it("filters by query and shows results", () => {
    render(<Harness onChange={() => {}} />);
    const input = screen.getByRole("combobox", { name: "From" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "lon" } });
    expect(screen.getByRole("option", { name: /Heathrow/ })).toBeTruthy();
    expect(screen.queryByRole("option", { name: /Dublin/ })).toBeNull();
  });

  it("shows an honest empty state for no matches", () => {
    render(<Harness onChange={() => {}} />);
    const input = screen.getByRole("combobox", { name: "From" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "zzzz" } });
    expect(screen.getByText("No matching airports")).toBeTruthy();
  });

  it("selects an airport by click and yields its UUID (never free text)", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const input = screen.getByRole("combobox", { name: "From" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "dub" } });
    fireEvent.mouseDown(screen.getByRole("option", { name: /Dublin/ }));
    expect(onChange).toHaveBeenLastCalledWith(A1);
  });

  it("is keyboard-usable: ArrowDown + Enter selects a real airport id", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const input = screen.getByRole("combobox", { name: "From" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "" } }); // all results
    fireEvent.keyDown(input, { key: "ArrowDown" }); // move to index 1 (Heathrow)
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenLastCalledWith(A2);
  });

  it("typing after a selection clears the prior value (no stale UUID)", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const input = screen.getByRole("combobox", { name: "From" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "dub" } });
    fireEvent.mouseDown(screen.getByRole("option", { name: /Dublin/ }));
    expect(onChange).toHaveBeenLastCalledWith(A1);
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "hea" } });
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("renders a field error with an alert role", () => {
    render(
      <AirportPicker
        id="pick"
        label="From"
        airports={AIRPORTS}
        value={null}
        onChange={() => {}}
        error="Select a departure airport."
      />,
    );
    expect(screen.getByRole("alert").textContent).toContain(
      "Select a departure airport.",
    );
  });
});
