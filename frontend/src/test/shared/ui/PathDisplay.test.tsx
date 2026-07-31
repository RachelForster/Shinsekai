import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PathDisplay } from "../../../shared/ui";

describe("PathDisplay", () => {
  it("renders the file name portion", () => {
    render(<PathDisplay path="/home/user/data.txt" />);
    expect(screen.getByText("data.txt")).toBeInTheDocument();
  });

  it("renders the directory prefix", () => {
    render(<PathDisplay path="/home/user/data.txt" />);
    expect(screen.getByText("/home/user/")).toBeInTheDocument();
  });

  it("renders full path when no directory separator", () => {
    render(<PathDisplay path="readme.md" />);
    expect(screen.getByText("readme.md")).toBeInTheDocument();
  });

  it("keeps the Windows drive prefix separate from the file name", () => {
    const prefixPath = ["C:", "Users", "Tester", "Pictures"].join("\\") + "\\";
    const path = `${prefixPath}scene.png`;
    const { container } = render(<PathDisplay path={path} />);
    const prefix = container.querySelector(".path-display__prefix");
    const name = container.querySelector(".path-display__name");

    expect(prefix?.textContent).toBe(prefixPath);
    expect(name?.textContent).toBe("scene.png");
  });

  it("keeps UNC prefixes separate from the file name", () => {
    const prefixPath = "\\\\" + ["server", "share", "folder"].join("\\") + "\\";
    const path = `${prefixPath}scene.png`;
    const { container } = render(<PathDisplay path={path} />);
    const prefix = container.querySelector(".path-display__prefix");
    const name = container.querySelector(".path-display__name");

    expect(prefix?.textContent).toBe(prefixPath);
    expect(name?.textContent).toBe("scene.png");
  });

  it("splits mixed-separator UNC paths without treating them as POSIX names", () => {
    const path = String.raw`//server/share/folder\scene.png`;
    const { container } = render(<PathDisplay path={path} />);

    expect(container.querySelector(".path-display__prefix")?.textContent).toBe("//server/share/folder\\");
    expect(container.querySelector(".path-display__name")?.textContent).toBe("scene.png");
  });

  it("keeps a literal POSIX backslash in the filename identity", () => {
    const { container } = render(<PathDisplay path={String.raw`/tmp/uploads/voice\alternate.wav`} />);
    const prefix = container.querySelector(".path-display__prefix");
    const name = container.querySelector(".path-display__name");

    expect(prefix?.textContent).toBe("/tmp/uploads/");
    expect(name?.textContent).toBe(String.raw`voice\alternate.wav`);
  });

  it("sets title attribute to full path", () => {
    const path = "/home/user/file.txt";
    render(<PathDisplay path={path} />);
    expect(screen.getByTitle(path)).toBeInTheDocument();
  });
});
