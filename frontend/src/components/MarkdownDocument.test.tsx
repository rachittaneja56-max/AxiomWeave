import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MarkdownDocument } from "./MarkdownDocument";

afterEach(cleanup);

describe("MarkdownDocument duplicate heading suppression", () => {
  it("suppresses a leading matching H1/H2 at render time", () => {
    render(
      <MarkdownDocument
        content={"## Executive Summary\n\nThe pilot begins in November."}
        suppressFirstHeading="Executive Summary"
      />,
    );

    expect(
      screen.queryByRole("heading", { name: "Executive Summary" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("The pilot begins in November."),
    ).toBeInTheDocument();
  });

  it("keeps a first heading when it differs from the artifact label", () => {
    render(
      <MarkdownDocument
        content={"# Key Findings\n\nThe pilot begins in November."}
        suppressFirstHeading="Executive Summary"
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Key Findings" }),
    ).toBeInTheDocument();
  });
});
