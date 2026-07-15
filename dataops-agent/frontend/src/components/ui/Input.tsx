import { InputHTMLAttributes, SelectHTMLAttributes, forwardRef } from "react";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  hint?: string;
  error?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, hint, error, className = "", id, ...rest },
  ref
) {
  const classes = ["input", error ? "input-error" : "", className].filter(Boolean).join(" ");
  const inputEl = <input ref={ref} id={id} className={classes} {...rest} />;

  if (!label && !hint && !error) return inputEl;

  return (
    <div className="input-group">
      {label && (
        <label className="input-label" htmlFor={id}>
          {label}
        </label>
      )}
      {inputEl}
      {error ? <span className="input-hint text-danger">{error}</span> : hint ? <span className="input-hint">{hint}</span> : null}
    </div>
  );
});

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  hint?: string;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { label, hint, className = "", id, children, ...rest },
  ref
) {
  const classes = ["input", "select", className].filter(Boolean).join(" ");
  const selectEl = (
    <select ref={ref} id={id} className={classes} {...rest}>
      {children}
    </select>
  );

  if (!label && !hint) return selectEl;

  return (
    <div className="input-group">
      {label && (
        <label className="input-label" htmlFor={id}>
          {label}
        </label>
      )}
      {selectEl}
      {hint && <span className="input-hint">{hint}</span>}
    </div>
  );
});
