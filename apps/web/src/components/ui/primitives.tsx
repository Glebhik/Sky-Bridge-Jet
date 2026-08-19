import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
} from "react";

/**
 * Foundational, presentational UI primitives for the Customer Portal shell. They carry no
 * business logic and no client state, so they compose in both server and client
 * components. Styling is class-based against the tokens in `globals.css` — no UI library.
 */

export function Container({ children }: { children: ReactNode }) {
  return <div className="container">{children}</div>;
}

export function PageHeading({
  title,
  description,
}: {
  title: string;
  description?: string;
}) {
  return (
    <header className="page-heading">
      <h1>{title}</h1>
      {description ? (
        <p className="page-heading__description">{description}</p>
      ) : null}
    </header>
  );
}

export function Card({
  children,
  as: Tag = "section",
}: {
  children: ReactNode;
  as?: "section" | "article" | "div";
}) {
  return <Tag className="card">{children}</Tag>;
}

type BadgeTone = "neutral" | "info" | "success" | "warning" | "danger";

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: BadgeTone;
}) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}

type AlertTone = "info" | "error" | "warning" | "success";

export function Alert({
  tone = "info",
  title,
  children,
}: {
  tone?: AlertTone;
  title?: string;
  children?: ReactNode;
}) {
  return (
    <div
      className={`alert alert--${tone}`}
      role={tone === "error" ? "alert" : "status"}
    >
      {title ? <p className="alert__title">{title}</p> : null}
      {children ? <div className="alert__body">{children}</div> : null}
    </div>
  );
}

type ButtonVariant = "primary" | "secondary" | "ghost";

export function Button({
  variant = "primary",
  children,
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return (
    <button
      className={`button button--${variant}${className ? ` ${className}` : ""}`}
      {...props}
    >
      {children}
    </button>
  );
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="state state--loading" role="status" aria-busy="true">
      <span className="state__spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="state state--empty">
      <p className="state__title">{title}</p>
      {description ? <p className="state__description">{description}</p> : null}
      {action ? <div className="state__action">{action}</div> : null}
    </div>
  );
}

export function Field({
  label,
  id,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string; id: string }) {
  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      <input className="field__input" id={id} {...props} />
    </div>
  );
}
