"use client";

import { useId, useMemo, useRef, useState } from "react";

import type { Airport } from "@/lib/api/types";
import { airportOptionLabel, filterAirports } from "@/lib/portal/trip-create";

/**
 * An accessible origin/destination airport picker built against the real `GET /airports`
 * contract (all active airports, no server-side search): the parent fetches the list once and
 * passes it in; this component filters client-side and yields the selected airport's UUID.
 *
 * It is a keyboard-usable combobox — type to filter, Arrow Up/Down to move, Enter to choose,
 * Escape to close — with `role="combobox"`/`listbox`/`option`, `aria-activedescendant`, and a
 * clear selected state. It never submits free text: only choosing a listed airport sets a
 * value, and the value is always a real airport id (never a typed string).
 */
export interface AirportPickerProps {
  readonly id: string;
  readonly label: string;
  readonly airports: readonly Airport[];
  readonly value: string | null;
  readonly onChange: (airportId: string | null) => void;
  readonly error?: string;
  readonly disabled?: boolean;
}

export function AirportPicker({
  id,
  label,
  airports,
  value,
  onChange,
  error,
  disabled,
}: AirportPickerProps) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const listId = useId();
  const errorId = useId();
  const blurTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const selected = useMemo(
    () => airports.find((airport) => airport.id === value) ?? null,
    [airports, value],
  );
  const results = useMemo(
    () => filterAirports(airports, query),
    [airports, query],
  );

  // When an airport is selected and the field is closed, show its label; otherwise the query.
  const inputValue = open
    ? query
    : selected
      ? airportOptionLabel(selected)
      : "";

  function choose(airport: Airport): void {
    onChange(airport.id);
    setQuery("");
    setOpen(false);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>): void {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!open) setOpen(true);
      setActiveIndex((index) => Math.min(index + 1, results.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter") {
      if (open && results[activeIndex]) {
        event.preventDefault();
        choose(results[activeIndex]);
      }
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div className="field airport-picker">
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className="field__input"
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={
          open && results[activeIndex]
            ? `${listId}-option-${activeIndex}`
            : undefined
        }
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        autoComplete="off"
        disabled={disabled}
        value={inputValue}
        placeholder="Search by city, name, or code"
        onFocus={() => {
          if (blurTimer.current) clearTimeout(blurTimer.current);
          setOpen(true);
        }}
        onBlur={() => {
          // Delay so an option's mousedown can register before we close.
          blurTimer.current = setTimeout(() => setOpen(false), 120);
        }}
        onChange={(event) => {
          setQuery(event.target.value);
          setActiveIndex(0);
          setOpen(true);
          if (value !== null) onChange(null); // typing clears a prior selection
        }}
        onKeyDown={handleKeyDown}
      />
      {open ? (
        <ul className="airport-picker__list" role="listbox" id={listId}>
          {results.length === 0 ? (
            <li className="airport-picker__empty" role="presentation">
              No matching airports
            </li>
          ) : (
            results.map((airport, index) => (
              <li
                key={airport.id}
                id={`${listId}-option-${index}`}
                role="option"
                aria-selected={airport.id === value}
                className={
                  index === activeIndex
                    ? "airport-picker__option airport-picker__option--active"
                    : "airport-picker__option"
                }
                // onMouseDown (not onClick) so selection wins the race with input blur.
                onMouseDown={(event) => {
                  event.preventDefault();
                  choose(airport);
                }}
              >
                {airportOptionLabel(airport)}
              </li>
            ))
          )}
        </ul>
      ) : null}
      {selected && !open ? (
        <p className="airport-picker__selected">Selected: {selected.name}</p>
      ) : null}
      {error ? (
        <p id={errorId} className="field__error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
