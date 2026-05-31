import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DataTable } from "../../../shared/ui";

interface TestRow {
  id: string;
  name: string;
}

describe("DataTable", () => {
  const columns = [
    { key: "name", header: "名称", render: (row: TestRow) => row.name },
    { key: "id", header: "ID", render: (row: TestRow) => <code>{row.id}</code> },
  ];
  const rows: TestRow[] = [
    { id: "1", name: "Alice" },
    { id: "2", name: "Bob" },
  ];

  it("renders column headers", () => {
    render(<DataTable columns={columns} getRowKey={(r) => r.id} rows={rows} />);
    expect(screen.getByText("名称")).toBeInTheDocument();
    expect(screen.getByText("ID")).toBeInTheDocument();
  });

  it("renders all rows", () => {
    render(<DataTable columns={columns} getRowKey={(r) => r.id} rows={rows} />);
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("Bob")).toBeInTheDocument();
  });
});
