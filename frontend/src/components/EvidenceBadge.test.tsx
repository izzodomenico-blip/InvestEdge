import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DemoMarker, EvidenceBadge } from "./EvidenceBadge";
import type { EvidenceLatest, Verdict } from "../lib/api";
function latest(verdict: Verdict, horizon = 5): EvidenceLatest {
  const summary = { id: 1, job_id: 11, signal_name: "score", timeframe: "D" as const, horizon: horizon as 1|5|21,
    verdict, fingerprint: "abc", created_at: "2026-10-10T10:00:00Z" };
  return { signal_name: "score", timeframe: "D", best: summary,
    horizons: { "1": null, "5": summary, "21": null } };
}
describe("EvidenceBadge", () => {
  it.each([["VALIDATO", 5, "VALIDATO · 5g"], ["NON_VALIDATO", 1, "NON VALIDATO · 1g"],
    ["INSUFFICIENTE", 21, "INSUFFICIENTE · 21g"]] as const)("rende %s dal backend", (verdict, horizon, label) => {
    render(<EvidenceBadge latest={latest(verdict, horizon)} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });
  it("mostra NON MISURATO senza report", () => {
    render(<EvidenceBadge latest={null} />); expect(screen.getByText("NON MISURATO")).toBeInTheDocument();
  });
  it("DEMO prevale anche su un report VALIDATO", () => {
    render(<EvidenceBadge latest={latest("VALIDATO")} dataMode="DEMO" />);
    expect(screen.getByText("DEMO · non misurabile")).toBeInTheDocument();
    expect(screen.queryByText("VALIDATO · 5g")).not.toBeInTheDocument();
  });
  it("rispetta best e rende i tre orizzonti, date e ambito nel tooltip accessibile", () => {
    const value = latest("NON_VALIDATO", 1);
    value.horizons["21"] = { ...value.best!, horizon: 21, verdict: "VALIDATO" };
    render(<EvidenceBadge latest={value} />);
    const badge = screen.getByText("NON VALIDATO · 1g");
    expect(badge).toHaveAttribute("tabindex", "0");
    expect(badge).toHaveAttribute("title", expect.stringContaining("verdetto sul segnale nell'universo, non sul singolo titolo"));
    for (const label of ["1g", "5g", "21g", "2026-10-10"]) expect(badge.title).toContain(label);
  });
  it.each(["REAL", null, undefined] as const)("non marca %s come DEMO", (mode) => {
    render(<DemoMarker dataMode={mode} />); expect(screen.queryByText("DEMO")).not.toBeInTheDocument();
  });
  it("marca solo DEMO", () => { render(<DemoMarker dataMode="DEMO" />); expect(screen.getByText("DEMO")).toBeInTheDocument(); });
});
