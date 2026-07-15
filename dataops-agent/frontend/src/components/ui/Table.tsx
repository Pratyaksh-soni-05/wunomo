import { HTMLAttributes, ReactNode, TdHTMLAttributes, ThHTMLAttributes } from "react";

export function Table({ className = "", children, ...rest }: HTMLAttributes<HTMLTableElement>) {
  return (
    <div className="table-wrap">
      <table className={className} {...rest}>
        {children}
      </table>
    </div>
  );
}

export function Thead({ children }: { children?: ReactNode }) {
  return <thead>{children}</thead>;
}

export function Tbody({ children }: { children?: ReactNode }) {
  return <tbody>{children}</tbody>;
}

interface RowProps extends HTMLAttributes<HTMLTableRowElement> {
  selected?: boolean;
  children?: ReactNode;
}

export function Tr({ selected = false, className = "", children, ...rest }: RowProps) {
  const classes = [selected ? "selected" : "", className].filter(Boolean).join(" ");
  return (
    <tr className={classes || undefined} {...rest}>
      {children}
    </tr>
  );
}

export function Th({ children, ...rest }: ThHTMLAttributes<HTMLTableCellElement>) {
  return <th {...rest}>{children}</th>;
}

export function Td({ children, ...rest }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td {...rest}>{children}</td>;
}
